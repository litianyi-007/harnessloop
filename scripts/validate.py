#!/usr/bin/env python3
"""Cross-platform Harnessloop repository validation.

Checks, in order:
1. Manifest and marketplace invariants (Codex + Claude).
2. Init smoke test (skeleton creation, intake packet).
3. Setup completeness smoke test (check_setup.py) on a skeleton project and a
   programmatically-filled fixture, including the double-gate (gate_blocking
   vs complete) regression cases.
4. Secrets smoke test (channel-params store, gitignore protection, no values).
5. Documentation skeleton consistency against init_project.py (single source of truth).
6. Mechanical protocol gates (verify_protocol.py) on examples/mock-project,
   including negative fixtures that must fail.
7. Round cost settlement smoke test (round_cost.py) on a synthetic transcript.
8. Claude strict plugin validation (skippable via HARNESSLOOP_SKIP_CLAUDE=1
   for environments without the claude CLI, e.g. bare CI runners).

Exit code 0 = all passed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import subprocess
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "harnessloop"
LOOP_SCRIPTS = PLUGIN_ROOT / "skills" / "harnessloop-loop" / "scripts"

sys.path.insert(0, str(LOOP_SCRIPTS))
import init_project  # noqa: E402
import verify_protocol  # noqa: E402
import check_setup  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  ok: {message}")
    else:
        print(f"  FAIL: {message}")
        FAILURES.append(message)


def read_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_python(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def validate_manifests() -> None:
    print("[1/8] Manifests and marketplace entries")
    codex_manifest = read_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")
    codex_marketplace = read_json(REPO_ROOT / ".agents" / "plugins" / "marketplace.json")
    claude_manifest = read_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")
    claude_marketplace = read_json(REPO_ROOT / ".claude-plugin" / "marketplace.json")

    check(codex_manifest.get("name") == "harnessloop", "Codex plugin name is harnessloop")
    check(claude_manifest.get("name") == "harnessloop", "Claude plugin name is harnessloop")

    codex_entry = next((p for p in codex_marketplace.get("plugins", []) if p.get("name") == "harnessloop"), None)
    check(codex_entry is not None, "Codex marketplace has harnessloop entry")
    if codex_entry:
        source = codex_entry.get("source", {})
        check(
            source.get("source") == "local" and source.get("path") == "./plugins/harnessloop",
            "Codex marketplace entry points to local ./plugins/harnessloop",
        )
        policy = codex_entry.get("policy", {})
        check(
            policy.get("installation") == "AVAILABLE" and policy.get("authentication") == "ON_INSTALL",
            "Codex marketplace policy is AVAILABLE / ON_INSTALL",
        )

    claude_entry = next((p for p in claude_marketplace.get("plugins", []) if p.get("name") == "harnessloop"), None)
    check(claude_entry is not None, "Claude marketplace has harnessloop entry")
    if claude_entry:
        check(
            claude_entry.get("source") == "./plugins/harnessloop",
            "Claude marketplace entry points to ./plugins/harnessloop",
        )

    check((REPO_ROOT / "LICENSE").exists(), "LICENSE exists at repository root")
    package = read_json(REPO_ROOT / "package.json")
    check(package.get("license") == "Apache-2.0", "package.json declares Apache-2.0 license")
    scripts_blob = json.dumps(package.get("scripts", {}))
    check("powershell" not in scripts_blob.lower(), "npm scripts do not shell out to powershell")

    check(claude_manifest.get("license") == "Apache-2.0", "Claude plugin manifest declares Apache-2.0")
    check(codex_manifest.get("license") == "Apache-2.0", "Codex plugin manifest declares Apache-2.0")
    if claude_entry:
        check(claude_entry.get("license") == "Apache-2.0", "Claude marketplace entry declares Apache-2.0")
    if codex_entry:
        check(codex_entry.get("license") == "Apache-2.0", "Codex marketplace entry declares Apache-2.0")


def validate_init_smoke() -> None:
    print("[2/8] Init smoke test")
    smoke_root = REPO_ROOT / ".tmp" / f"init-smoke-{uuid.uuid4().hex}"
    smoke_root.mkdir(parents=True)
    try:
        result = run_python(LOOP_SCRIPTS / "init_project.py", "--project", str(smoke_root), "--intake", "smoke-task", "--json")
        check(result.returncode == 0, "init_project.py exits 0")
        if result.returncode != 0:
            print(result.stdout + result.stderr)
            return

        expected = list(init_project.BASE_FILES) + list(init_project.LOCAL_FILES) + list(init_project.INTAKE_FILES)
        for rel in expected:
            check((smoke_root / rel).exists(), f"init creates {rel}")

        packets = list((smoke_root / ".harnessloop" / "intake").rglob("transfer-packet.md"))
        check(len(packets) == 1, "init --intake creates exactly one transfer-packet.md")
    finally:
        shutil.rmtree(smoke_root, ignore_errors=True)


def _fill_setup_project(root: Path) -> None:
    """Programmatically fill every leaf field / table slot check_setup.py's
    manifest defines, deriving edit locations directly from
    check_setup.MANIFEST / locate_field_line / locate_table_bounds so this
    fixture can never drift out of sync with the detector it exercises
    (design-v2 section 7.2 bullet 2: deliberately not reusing
    examples/mock-project, whose structure is already known to lag the
    current templates).
    """
    init_project.initialize(root, None, False, False)
    for rel in check_setup.FILES_ORDER:
        path = root / rel
        spec = check_setup.MANIFEST[rel]
        text = path.read_text(encoding="utf-8")

        if spec["fields"]:
            lines = text.splitlines()
            for heading, container, label in spec["fields"]:
                idx = check_setup.locate_field_line(text, rel, heading, container, label)
                if idx is None:
                    raise AssertionError(f"fixture: cannot locate field {label!r} in {rel}")
                lines[idx] = check_setup.render_leaf_value(lines[idx], label, "value")
            text = "\n".join(lines) + "\n"

        for heading in spec["tables"]:
            bounds = check_setup.locate_table_bounds(text, heading)
            if bounds is None:
                raise AssertionError(f"fixture: cannot locate table {heading!r} in {rel}")
            sep_idx, _slice_end = bounds
            lines = text.splitlines()
            lines.insert(sep_idx + 1, check_setup.render_sentinel_line(heading))
            text = "\n".join(lines) + "\n"

        path.write_text(text, encoding="utf-8")


def _run_check_setup(project: Path) -> subprocess.CompletedProcess:
    return run_python(LOOP_SCRIPTS / "check_setup.py", "--project", str(project), "--json")


def _run_check_setup_json(project: Path, expected_exit: int, label: str) -> dict:
    result = _run_check_setup(project)
    check(result.returncode == expected_exit, f"{label}: check_setup.py exits {expected_exit}")
    if result.returncode != expected_exit or not result.stdout.strip():
        print(result.stdout + result.stderr)
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout + result.stderr)
        return {}


def validate_check_setup_smoke() -> None:
    """Stage 3: setup-completeness smoke test (check_setup.py).

    Known limitation (hopper T-001 review, Finding 5 / TH-0009 -- accepted,
    NOT fixed this round): the "filled"/"partial"/reverted-to-template
    fixtures below (`_fill_setup_project` and its callers) are built by
    driving `check_setup.MANIFEST`, `check_setup.locate_field_line`, and
    `check_setup.locate_table_bounds` directly -- the exact same manifest
    and slicing logic `check_setup.py` itself uses to detect completeness.
    A field the manifest omits, or a locator bug that mis-slices a
    heading/container identically in both the fixture writer and the
    detector, can therefore self-confirm: fixture and detector would agree
    with each other while both silently disagreeing with the actual wizard
    templates. Considered and deferred this round: MANIFEST already
    hand-transcribes 60+ leaf fields from the templates once (round 0003);
    an independently hand-authored fixture would duplicate that
    transcription surface (and its own drift risk) to guard against a
    narrower defect class than the two concrete, independently-reproduced
    detection bugs (empty pipe rows, wrong-category sentinels) actually
    fixed here. Tracked in TH-0009 for a future cost/benefit revisit rather
    than silently ignored.
    """
    print("[3/8] Setup completeness smoke test (check_setup.py)")

    # 1. Bare skeleton: incomplete + gate_blocking (design-v2 section 7.2
    # bullet 1). All 3 core policy files (environment, control-contract,
    # cost-context-policy) are still `template`.
    bare_root = REPO_ROOT / ".tmp" / f"check-setup-bare-{uuid.uuid4().hex}"
    bare_root.mkdir(parents=True)
    try:
        init_project.initialize(bare_root, None, False, False)
        report = _run_check_setup_json(bare_root, 1, "bare skeleton")
        check(report.get("complete") is False, "bare skeleton: complete=false")
        check(report.get("filled") == 0, "bare skeleton: filled=0")
        check(report.get("total") == 5, "bare skeleton: total=5")
        check(report.get("gate_blocking") is True, "bare skeleton: gate_blocking=true (all 3 core files template)")
        check(report.get("field_todo_count") == 0, "bare skeleton: field_todo_count=0")
        check(report.get("selfcheck_todo_count") == 0, "bare skeleton: selfcheck_todo_count=0")
    finally:
        shutil.rmtree(bare_root, ignore_errors=True)

    # M-B regression (adversarial review, round 0003): a stray prose line
    # left in an otherwise-empty table section -- neither a real `|`-prefixed
    # row nor the S1 sentinel -- must not count as "answered". Pre-fix,
    # `_resolve_table` treated any non-blank line after the separator as a
    # data row, bypassing the sentinel anchor entirely; this assertion must
    # fail against that code.
    prose_root = REPO_ROOT / ".tmp" / f"check-setup-prose-{uuid.uuid4().hex}"
    prose_root.mkdir(parents=True)
    try:
        init_project.initialize(prose_root, None, False, False)
        ds_path = prose_root / ".harnessloop/setup/data-sources.md"
        text = ds_path.read_text(encoding="utf-8")
        bounds = check_setup.locate_table_bounds(text, "Static Sources")
        if bounds is None:
            raise AssertionError("fixture: cannot locate Static Sources table bounds")
        sep_idx, _slice_end = bounds
        lines = text.splitlines()
        lines.insert(sep_idx + 1, "not sure yet, need to check with the data team")
        ds_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = _run_check_setup_json(prose_root, 1, "M-B: prose line in empty table")
        ds_report = report.get("files", {}).get(".harnessloop/setup/data-sources.md", {})
        check(
            ds_report.get("state") == "template",
            f"M-B: data-sources.md stays template with a prose line and no real row/sentinel "
            f"(got state={ds_report.get('state')!r})",
        )
        check(
            ds_report.get("fields_filled") == 0,
            f"M-B: Static Sources not counted as filled by a prose line (got fields_filled={ds_report.get('fields_filled')!r})",
        )
        check(
            "Static Sources" in ds_report.get("missing_sections", []),
            f"M-B: Static Sources still listed in missing_sections (got {ds_report.get('missing_sections')!r})",
        )
    finally:
        shutil.rmtree(prose_root, ignore_errors=True)

    # T-001 Finding 1 regression (hopper review, TH-0009): an all-empty
    # markdown row (`|  |  |`, the raw template row shape) left under an
    # otherwise-empty table section must not count as a real data row.
    # Pre-fix, `_resolve_table` counted any post-separator line starting
    # with `|` as a data row regardless of cell contents; this assertion
    # must fail against that code (independently confirmed by temporarily
    # reverting the fix -- see TH-0009).
    empty_row_root = REPO_ROOT / ".tmp" / f"check-setup-emptyrow-{uuid.uuid4().hex}"
    empty_row_root.mkdir(parents=True)
    try:
        init_project.initialize(empty_row_root, None, False, False)
        ds_path = empty_row_root / ".harnessloop/setup/data-sources.md"
        text = ds_path.read_text(encoding="utf-8")
        bounds = check_setup.locate_table_bounds(text, "Static Sources")
        if bounds is None:
            raise AssertionError("fixture: cannot locate Static Sources table bounds")
        sep_idx, _slice_end = bounds
        lines = text.splitlines()
        lines.insert(sep_idx + 1, "|  |  |")
        ds_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = _run_check_setup_json(empty_row_root, 1, "T-001#1: all-empty pipe row in table")
        ds_report = report.get("files", {}).get(".harnessloop/setup/data-sources.md", {})
        check(
            ds_report.get("state") == "template",
            f"T-001#1: data-sources.md stays template with an all-empty pipe row "
            f"and no real row/sentinel (got state={ds_report.get('state')!r})",
        )
        check(
            "Static Sources" in ds_report.get("missing_sections", []),
            f"T-001#1: Static Sources still listed in missing_sections with an empty pipe row "
            f"(got {ds_report.get('missing_sections')!r})",
        )
    finally:
        shutil.rmtree(empty_row_root, ignore_errors=True)

    # T-001 Finding 2 regression (hopper review, TH-0009): a syntactically
    # valid S1 sentinel written for the WRONG category (the "Dynamic Or
    # Generated Sources" sentinel pasted under the "Static Sources" table)
    # must not count as Static Sources being answered. Pre-fix, the sentinel
    # regex matched generic "no/none ... (confirmed via setup wizard)"
    # wording without binding to the current heading's own category text;
    # this assertion must fail against that code (independently confirmed by
    # temporarily reverting the fix -- see TH-0009).
    wrong_sentinel_root = REPO_ROOT / ".tmp" / f"check-setup-wrongsentinel-{uuid.uuid4().hex}"
    wrong_sentinel_root.mkdir(parents=True)
    try:
        init_project.initialize(wrong_sentinel_root, None, False, False)
        ds_path = wrong_sentinel_root / ".harnessloop/setup/data-sources.md"
        text = ds_path.read_text(encoding="utf-8")
        bounds = check_setup.locate_table_bounds(text, "Static Sources")
        if bounds is None:
            raise AssertionError("fixture: cannot locate Static Sources table bounds")
        sep_idx, _slice_end = bounds
        lines = text.splitlines()
        wrong_sentinel = check_setup.render_sentinel_line("Dynamic Or Generated Sources")
        lines.insert(sep_idx + 1, wrong_sentinel)
        ds_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = _run_check_setup_json(wrong_sentinel_root, 1, "T-001#2: wrong-category sentinel")
        ds_report = report.get("files", {}).get(".harnessloop/setup/data-sources.md", {})
        check(
            ds_report.get("state") == "template",
            f"T-001#2: data-sources.md stays template when Static Sources holds the "
            f"Dynamic Or Generated Sources sentinel (got state={ds_report.get('state')!r})",
        )
        check(
            "Static Sources" in ds_report.get("missing_sections", []),
            f"T-001#2: Static Sources still listed in missing_sections with a wrong-category "
            f"sentinel (got {ds_report.get('missing_sections')!r})",
        )
    finally:
        shutil.rmtree(wrong_sentinel_root, ignore_errors=True)

    # 3. Usage error: nonexistent project path exits 2 (bullet 3).
    missing_root = REPO_ROOT / ".tmp" / f"check-setup-missing-{uuid.uuid4().hex}"
    result = _run_check_setup(missing_root)
    check(result.returncode == 2, "check_setup.py exits 2 for a nonexistent project path")

    # 2. Programmatically-filled fixture: complete, no TODOs (bullet 2).
    filled_root = REPO_ROOT / ".tmp" / f"check-setup-filled-{uuid.uuid4().hex}"
    filled_root.mkdir(parents=True)
    try:
        _fill_setup_project(filled_root)
        report = _run_check_setup_json(filled_root, 0, "filled fixture")
        check(report.get("complete") is True, "filled fixture: complete=true")
        check(report.get("filled") == 5, "filled fixture: filled=5")
        check(report.get("total") == 5, "filled fixture: total=5")
        check(report.get("gate_blocking") is False, "filled fixture: gate_blocking=false")
        check(report.get("field_todo_count") == 0, "filled fixture: field_todo_count=0")
        check(report.get("selfcheck_todo_count") == 0, "filled fixture: selfcheck_todo_count=0")
    finally:
        shutil.rmtree(filled_root, ignore_errors=True)

    # 4. Partial + non-core gap must NOT block (M1 core regression guard,
    # bullet 4). Reset data-sources.md's External Tools And Platforms table
    # back to template state on a fresh copy of the filled fixture.
    partial_root = REPO_ROOT / ".tmp" / f"check-setup-partial-{uuid.uuid4().hex}"
    partial_root.mkdir(parents=True)
    try:
        _fill_setup_project(partial_root)
        ds_path = partial_root / ".harnessloop/setup/data-sources.md"
        sentinel = check_setup.render_sentinel_line("External Tools And Platforms")
        lines = [line for line in ds_path.read_text(encoding="utf-8").splitlines() if line != sentinel]
        ds_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = _run_check_setup_json(partial_root, 1, "partial fixture (non-core gap)")
        ds_state = report.get("files", {}).get(".harnessloop/setup/data-sources.md", {}).get("state")
        check(ds_state == "partial", f"data-sources.md reports partial (got {ds_state!r})")
        check(report.get("complete") is False, "partial fixture: complete=false")
        check(
            report.get("gate_blocking") is False,
            "partial fixture: gate_blocking=false (non-core file partial does not block; M1 regression guard)",
        )
    finally:
        shutil.rmtree(partial_root, ignore_errors=True)

    # 5. Core file reverted to template must block (M1 core regression
    # guard, bullet 5).
    blocking_root = REPO_ROOT / ".tmp" / f"check-setup-blocking-{uuid.uuid4().hex}"
    blocking_root.mkdir(parents=True)
    try:
        _fill_setup_project(blocking_root)
        cc_path = blocking_root / ".harnessloop/state/control-contract.md"
        cc_path.write_text(init_project.read_template("control-contract-template.md"), encoding="utf-8")

        report = _run_check_setup_json(blocking_root, 1, "core file reverted to template")
        check(report.get("gate_blocking") is True, "control-contract.md reverted to template: gate_blocking=true")
        check(
            report.get("next_step") == ".harnessloop/state/control-contract.md",
            f"next_step points at control-contract.md (got {report.get('next_step')!r})",
        )
    finally:
        shutil.rmtree(blocking_root, ignore_errors=True)

    # 6. TODO visibility (bullet 6): a literal `TODO (owner: user)` value
    # still counts as filled, but must not be silent -- field_todo_count
    # must surface it. (selfcheck_todo_count is the separate, sanctioned
    # deviation from design-v2's single todo_count field -- see round
    # 0003-02 handoff and check_setup.py's module docstring.)
    todo_root = REPO_ROOT / ".tmp" / f"check-setup-todo-{uuid.uuid4().hex}"
    todo_root.mkdir(parents=True)
    try:
        _fill_setup_project(todo_root)
        ccp_rel = ".harnessloop/setup/cost-context-policy.md"
        ccp_path = todo_root / ccp_rel
        text = ccp_path.read_text(encoding="utf-8")
        idx = check_setup.locate_field_line(text, ccp_rel, "Main Session", "Responsibilities", "Orchestration")
        lines = text.splitlines()
        lines[idx] = check_setup.render_leaf_value(lines[idx], "Orchestration", check_setup.TODO_LITERAL)
        ccp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = _run_check_setup_json(todo_root, 0, "literal TODO value")
        ccp_state = report.get("files", {}).get(ccp_rel, {}).get("state")
        check(ccp_state == "filled", f"literal TODO value still counts as filled (got {ccp_state!r})")
        check(
            report.get("field_todo_count", 0) >= 1,
            f"field_todo_count surfaces the literal TODO (got {report.get('field_todo_count')!r})",
        )
    finally:
        shutil.rmtree(todo_root, ignore_errors=True)

    # PR-0 future-guard (external-citation-base-spec-20260727.md §2.2/§7):
    # a declared external reference-roots file must never enter check_setup.py's
    # 5-file completeness gate -- that would silently make an optional,
    # most-projects-don't-use-it capability inflate the wizard's headline
    # N/total number and turn two artifacts (this gate + the reference-roots
    # declaration) into a drift-prone pair. Welded assertion, not a behavior
    # test: if a future change ever adds a reference-roots file to FILES_ORDER,
    # `len(...) == 5` alone already goes red (and the "total=5" assertions
    # above would too), independent of what the file happens to be named.
    check(
        len(check_setup.FILES_ORDER) == 5
        and not any("reference" in rel.lower() for rel in check_setup.FILES_ORDER),
        "check_setup.py's FILES_ORDER stays at exactly 5 files and never names a "
        "reference-root file (external reference roots are declared in "
        ".harnessloop/setup/, not gated by the setup-completeness wizard)",
    )


def validate_secrets_smoke() -> None:
    print("[4/8] Secrets smoke test")
    secrets_script = PLUGIN_ROOT / "skills" / "harnessloop-secrets" / "scripts" / "channel_params.py"
    smoke_root = REPO_ROOT / ".tmp" / f"secrets-smoke-{uuid.uuid4().hex}"
    smoke_root.mkdir(parents=True)
    try:
        result = run_python(secrets_script, "--project", str(smoke_root), "init")
        check(result.returncode == 0, "channel_params.py init exits 0")

        result = run_python(
            secrets_script,
            "--project", str(smoke_root),
            "add",
            "--channel", "smoke-ci",
            "--key", "SMOKE_TOKEN",
            "--sensitivity", "secret",
            "--storage", "env",
            "--env", "SMOKE_TOKEN",
            "--required-for", "connectivity",
        )
        check(result.returncode == 2, "add reports missing env status (exit 2)")

        store_path = smoke_root / ".harnessloop" / "local" / "channel-params.json"
        ignore_path = smoke_root / ".harnessloop" / "local" / ".gitignore"
        check(store_path.exists(), "local store channel-params.json exists")
        check(
            ignore_path.exists() and "channel-params.json" in ignore_path.read_text(encoding="utf-8"),
            "local .gitignore protects channel-params.json",
        )

        store = json.loads(store_path.read_text(encoding="utf-8"))
        param = store["channels"]["smoke-ci"]["parameters"]["SMOKE_TOKEN"]
        check(
            param.get("sensitivity") == "secret" and param.get("storage") == "env" and param.get("env") == "SMOKE_TOKEN",
            "parameter metadata round-trips",
        )
        check(param.get("value") is None, "secret value is never written by add")
    finally:
        shutil.rmtree(smoke_root, ignore_errors=True)


def skeleton_entries() -> tuple[set[str], set[str]]:
    """Authoritative skeleton from init_project.py constants."""
    dirs = {rel.removeprefix(".harnessloop/") for rel in init_project.BASE_DIRS}
    files = {
        rel.removeprefix(".harnessloop/")
        for mapping in (init_project.BASE_FILES, init_project.LOCAL_FILES, init_project.INTAKE_FILES)
        for rel in mapping
    }
    return dirs, files


def skeleton_blocks(text: str) -> str:
    """Concatenate fenced code blocks that draw the .harnessloop skeleton.

    Matching only inside skeleton blocks (not whole-document text) prevents a
    file dropped from the skeleton from being masked by a prose mention.
    """
    blocks: list[str] = []
    fence: list[str] | None = None
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if fence is not None:
                joined = "\n".join(fence)
                if ".harnessloop/" in joined:
                    blocks.append(joined)
                fence = None
            else:
                fence = []
            continue
        if fence is not None:
            fence.append(line)
    return "\n".join(blocks)


def validate_doc_consistency() -> None:
    print("[5/8] Documentation skeleton consistency (source of truth: init_project.py)")
    dirs, files = skeleton_entries()

    # usage.md documents the initializer output as a bullet list, not a tree.
    doc_paths = [
        (REPO_ROOT / "README.md", True),
        (REPO_ROOT / "docs" / "usage.md", False),
        (REPO_ROOT / "docs" / "harnessloop-framework.md", True),
        (PLUGIN_ROOT / "skills" / "harnessloop-loop" / "SKILL.md", True),
        (PLUGIN_ROOT / "skills" / "harnessloop-init" / "SKILL.md", True),
    ]

    for doc, tree_only in doc_paths:
        text = doc.read_text(encoding="utf-8")
        rel_doc = doc.relative_to(REPO_ROOT)
        scope = skeleton_blocks(text) if tree_only else text
        if ".harnessloop/" not in scope:
            check(False, f"{rel_doc} contains a .harnessloop skeleton block")
            continue
        missing_dirs = sorted(d for d in {top_level(x) for x in dirs} if d not in scope)
        missing_files = sorted(f for f in files if Path(f).name not in scope)
        check(not missing_dirs, f"{rel_doc} skeleton includes all top-level dirs (missing: {missing_dirs or 'none'})")
        check(not missing_files, f"{rel_doc} skeleton includes all init-created files (missing: {missing_files or 'none'})")


def top_level(rel: str) -> str:
    return rel.split("/")[0] + "/"


# G18 (PR-0, external-citation-base-spec-20260727.md §3/§5): the "IN" column
# window inside harnessloop-loop/SKILL.md's "### Mechanical Gate Boundary"
# section must be delimited by the section's own headings, never by a fixed
# character offset. A magic-number window (the prior `+ 4000` slice) silently
# stops reporting drift the moment the IN column grows past that offset --
# exactly the kind of "docstring says one thing, machine checks another"
# lie this repo's own E1/E18 checks exist to prevent. Returns `None` if either
# heading is missing (start heading, or the "OUT" heading that bounds the end).
OUT_HEADING_MARKER = "What it does **not** decide"


def mechanical_gate_boundary_window(skill_text: str) -> str | None:
    start = skill_text.find("### Mechanical Gate Boundary")
    if start == -1:
        return None
    end = skill_text.find(OUT_HEADING_MARKER, start)
    if end == -1:
        return None
    return skill_text[start:end]


def validate_protocol_gates() -> None:
    print("[6/8] Mechanical protocol gates (verify_protocol.py)")
    mock_project = REPO_ROOT / "examples" / "mock-project"
    violations, mock_coverage = verify_protocol.verify_project(mock_project)
    check(not violations, f"examples/mock-project passes verify ({len(violations)} violation(s))")
    for violation in violations:
        print(f"    {violation['kind']}: {violation['detail']}")
    # PR-0 zero-migration guard: examples/mock-project has no verify:ignore
    # markers and no shape-dropped citations today -- the three new fields
    # must read exactly 0 here, and violations must stay empty (already
    # asserted above), proving the new counters are additive-only.
    check(
        mock_coverage.get("citations_ignored_explicit") == 0
        and mock_coverage.get("citations_shape_dropped") == 0
        and mock_coverage.get("review_files_with_ignore") == 0,
        "PR-0 zero-migration: examples/mock-project (no ignore markers, no "
        "shape-dropped spans) reports all three new fields as 0 "
        f"(got {({k: mock_coverage.get(k) for k in ('citations_ignored_explicit', 'citations_shape_dropped', 'review_files_with_ignore')})})",
    )

    # Negative fixtures: verify must FAIL when rules are broken.
    fixture_root = REPO_ROOT / ".tmp" / f"verify-fixture-{uuid.uuid4().hex}"
    round_dir = fixture_root / ".harnessloop" / "goals" / "20260101-001-fixture" / "rounds" / "0001"
    try:
        (round_dir / "evidence" / "runtime").mkdir(parents=True)
        (round_dir / "reviews").mkdir(parents=True)
        (round_dir / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n- Write evidence under `rounds/0001/evidence/`.\n",
            encoding="utf-8",
        )
        (round_dir / "evidence" / "runtime" / "ok.md").write_text("in scope\n", encoding="utf-8")
        (round_dir / "reviews" / "review.md").write_text(
            "cites `.harnessloop/goals/20260101-001-fixture/rounds/0001/evidence/runtime/missing.md`\n"
            "and source file `src/app/missing_module.py`\n",
            encoding="utf-8",
        )
        violations, _coverage = verify_protocol.verify_project(fixture_root)
        kinds = {v["kind"] for v in violations}
        check("dangling-citation" in kinds, "verify catches dangling citations (negative fixture)")
        check("scope-lock-violation" in kinds, "verify catches out-of-scope writes (negative fixture)")
        dangling = [v for v in violations if v["kind"] == "dangling-citation"]
        check(
            any("src/app/missing_module.py" in v["detail"] for v in dangling),
            "verify checks source-file citations outside protocol prefixes",
        )

        # Table-format scope-lock (scope-lock-template.md style) must parse.
        (round_dir / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "| Path/data/tool | Allowed action | Limit |\n"
            "| --- | --- | --- |\n"
            "| rounds/0001/evidence/ | write | evidence only |\n"
            "| rounds/0001/reviews/ | write | reviews only |\n",
            encoding="utf-8",
        )
        (round_dir / "reviews" / "review.md").write_text("table-format scope lock round\n", encoding="utf-8")
        violations, _coverage = verify_protocol.verify_project(fixture_root)
        kinds = {v["kind"] for v in violations}
        check(
            "unparseable-allowed-changes" not in kinds and "scope-lock-violation" not in kinds,
            "verify accepts template-style table scope-locks",
        )
    finally:
        shutil.rmtree(fixture_root, ignore_errors=True)

    # E2(a) positive-must-fail fixture: a round with NO scope-lock.md and NO
    # evidence/ or reviews/ directories at all -- i.e., truly nothing on
    # disk to inspect. Before this round's fix, the missing-scope-lock check
    # was gated behind `if checked_files:`, so a round like this always
    # exited clean regardless of whether it had a scope-lock (the m7 gap,
    # harnessloop/adversarial-review-p0.md:101). This is the "unconditional"
    # half of the fix: scope-lock existence is now checked for every round
    # independent of whether it has artifacts, so this bare round must fail.
    # This also closes the existing-fixture blind spot noted in E2's plan:
    # every other fixture in this file pre-creates evidence/ and reviews/
    # before writing a scope-lock, so none of them could ever have exercised
    # this path.
    empty_root = REPO_ROOT / ".tmp" / f"verify-fixture-empty-{uuid.uuid4().hex}"
    empty_round_dir = empty_root / ".harnessloop" / "goals" / "20260104-001-fixture" / "rounds" / "0001"
    try:
        empty_round_dir.mkdir(parents=True)
        violations, coverage = verify_protocol.verify_project(empty_root)
        kinds = {v["kind"] for v in violations}
        check(
            "missing-scope-lock" in kinds,
            "verify catches a round with no scope-lock.md and no evidence/reviews at all (E2(a) unconditional check)",
        )
        check(
            coverage.get("rounds") == 1 and coverage.get("rounds_zero_inspected") == 1,
            f"coverage counts the empty round as rounds=1, rounds_zero_inspected=1 (got {coverage})",
        )
        check(
            coverage.get("rule_a_files") == 0 and coverage.get("rule_b_files") == 0,
            f"coverage attributes zero rule_a_files/rule_b_files to a round with no artifacts (got {coverage})",
        )
    finally:
        shutil.rmtree(empty_root, ignore_errors=True)

    # E4 teeth（双向 mutation）：Verdict/Residuals 同文件枚举矛盾必须两个方向
    # 都翻转，且缺字段绝不违规（这是 14 个既有 round 零迁移的保证）。
    e4_root = Path(tempfile.mkdtemp(prefix="harnessloop-e4-"))
    e4_round = e4_root / ".harnessloop" / "goals" / "20260104-001-fixture" / "rounds" / "0001"
    try:
        e4_round.mkdir(parents=True)
        (e4_round / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n| Path | Action | Limit |\n"
            "| --- | --- | --- |\n| `.harnessloop/` | write | fixture |\n",
            encoding="utf-8",
        )
        contradiction = (
            "# Decision\n\n- Feedback: positive\n- Verdict: pass\n"
            "- Residuals: L2 layer never ran in CI\n- Accepted: yes\n"
        )
        (e4_round / "decision.md").write_text(contradiction, encoding="utf-8")
        violations, _ = verify_protocol.verify_project(e4_root)
        check(
            "verdict-residual-contradiction" in {v["kind"] for v in violations},
            "verify catches `Verdict: pass` alongside a non-none `Residuals` (E4)",
        )

        (e4_round / "decision.md").write_text(
            contradiction.replace("- Verdict: pass", "- Verdict: pass-with-residual"),
            encoding="utf-8",
        )
        violations, _ = verify_protocol.verify_project(e4_root)
        check(
            "verdict-residual-contradiction" not in {v["kind"] for v in violations},
            "`pass-with-residual` with the same residual text is accepted (E4 reverse mutation)",
        )

        (e4_round / "decision.md").write_text(
            "# Decision\n\n- Feedback: positive\n- Accepted: yes\n", encoding="utf-8"
        )
        violations, _ = verify_protocol.verify_project(e4_root)
        check(
            "verdict-residual-contradiction" not in {v["kind"] for v in violations},
            "a decision.md with neither field is not a violation (E4 zero-migration guarantee)",
        )
    finally:
        shutil.rmtree(e4_root, ignore_errors=True)

    # E5(a) 反僵化护栏：协议不得要求任何人「声明自己做过 teeth / 证伪」。
    # 任何这类字段只能退化成一句自报套话——那是保证产生假绿的写法，正是本轮
    # 裁定 teeth 只进插件 CI、不进协议正文的理由。这条断言让该裁定可被机械守住。
    ossify_pat = re.compile(
        r"(state|declare|record|assert|confirm)[^.\n]{0,60}"
        r"(falsification|teeth|破坏性反证|证伪)[^.\n]{0,60}(was|were|has been|performed|done|executed)",
        re.IGNORECASE,
    )
    ossify_hits = []
    for scan_root in ((REPO_ROOT / "plugins" / "harnessloop" / "skills"), (REPO_ROOT / "scripts")):
        if not scan_root.exists():
            continue
        for f in scan_root.rglob("*"):
            if f.is_file() and f.suffix in {".md", ".py"} and f.name != "validate.py":
                if ossify_pat.search(f.read_text(encoding="utf-8", errors="ignore")):
                    ossify_hits.append(str(f.relative_to(REPO_ROOT)))
    check(
        not ossify_hits,
        "no skill or script requires a round to *declare* that falsification/teeth "
        f"was performed — such a field can only degrade into boilerplate (found: {ossify_hits})",
    )

    # E1<->E2 一致性（teeth #4）：SKILL.md 的 Mechanical Gate Boundary "IN" 列
    # 逐字声称与 coverage 字段一一对应。若两边漂移，那份边界声明就在撒谎——
    # 而它是一份没有机械牙的纪律文档，唯一可测的一点就是这个对应关系。
    # G18 (PR-0): the window is now heading-delimited (mechanical_gate_boundary_window),
    # not the prior fixed `+ 4000` offset -- see that function's docstring comment.
    skill_md = (
        REPO_ROOT / "plugins" / "harnessloop" / "skills" / "harnessloop-loop" / "SKILL.md"
    )
    if skill_md.exists():
        skill_text = skill_md.read_text(encoding="utf-8")
        boundary = mechanical_gate_boundary_window(skill_text)
        check(
            boundary is not None,
            "harnessloop-loop/SKILL.md declares the Mechanical Gate Boundary IN/OUT "
            "headings (E1/G18)",
        )
        if boundary is not None:
            _, sample_coverage = verify_protocol.verify_project(REPO_ROOT.parent)
            missing = [f for f in sample_coverage if f"`{f}`" not in boundary]
            check(
                not missing,
                "every coverage field is named in the SKILL.md IN column "
                f"(missing: {missing})",
            )

    # G18 sentinel-string teeth (PR-0): prove the window boundary is really
    # heading-delimited, not a re-introduced magic number, without any manual
    # step. Build a synthetic doc whose IN column is deliberately padded past
    # 4000 characters before its last bullet (`zzz_g18_sentinel_field`), and
    # whose OUT column carries its own field name that must never leak into
    # the IN-column window.
    print("  G18: coverage-key <-> SKILL.md IN-column window uses heading boundaries, not a magic number")
    g18_filler = "- filler bullet padding the IN column past the old fixed offset.\n" * 120
    g18_sentinel_in = "zzz_g18_sentinel_field"
    g18_sentinel_out = "zzz_g18_out_only_field"
    g18_synthetic = (
        "### Mechanical Gate Boundary\n\n"
        "What it currently checks (IN):\n\n"
        f"{g18_filler}"
        f"- `{g18_sentinel_in}` — placed past the 4000-character mark on purpose.\n\n"
        "What it does **not** decide (OUT):\n\n"
        f"- `{g18_sentinel_out}` — must never be visible to the IN-column window.\n"
    )
    g18_start = g18_synthetic.find("### Mechanical Gate Boundary")
    check(
        len(g18_synthetic) - g18_start > 4000,
        "G18 fixture sanity: the synthetic doc's IN column genuinely exceeds "
        "the old 4000-character offset (fixture would be vacuous otherwise)",
    )
    g18_window = mechanical_gate_boundary_window(g18_synthetic)
    check(
        g18_window is not None
        and f"`{g18_sentinel_in}`" in g18_window
        and f"`{g18_sentinel_out}`" not in g18_window,
        "G18: heading-delimited window reaches a sentinel field placed past the "
        "4000-character mark and stops before the OUT heading",
    )
    # Mutation control: the pre-G18 fixed-offset window would have missed the
    # sentinel entirely -- proving the assertion above has real teeth, not a
    # coincidental pass.
    g18_old_style_window = g18_synthetic[g18_start : g18_start + 4000]
    check(
        f"`{g18_sentinel_in}`" not in g18_old_style_window,
        "mutation control: a hardcoded `+ 4000` window would have missed the "
        "sentinel field (proves the G18 fixture is load-bearing, not vacuous)",
    )

    # Rule B pathish false-positive fixtures (evolution issue TH-0006): a
    # real project run turned up six false-positive dangling-citation hits
    # from regex/glob spans, a submodule-relative path, and bare-domain
    # URLs. Cover each exemption plus the explicit verify:ignore escape
    # hatch, and confirm a genuinely dangling citation is still caught
    # (must not trade false positives for false negatives).
    exempt_root = REPO_ROOT / ".tmp" / f"verify-fixture-exempt-{uuid.uuid4().hex}"
    round_dir2 = exempt_root / ".harnessloop" / "goals" / "20260102-001-fixture" / "rounds" / "0001"
    try:
        (round_dir2 / "evidence").mkdir(parents=True)
        (round_dir2 / "reviews").mkdir(parents=True)
        (round_dir2 / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )

        # A first-level git submodule with a real file, cited relative to
        # the submodule's own root rather than the project root.
        (exempt_root / ".gitmodules").write_text(
            '[submodule "vendorlib"]\n\tpath = vendorlib\n\turl = https://example.invalid/vendorlib.git\n',
            encoding="utf-8",
        )
        (exempt_root / "vendorlib" / "pkg").mkdir(parents=True)
        (exempt_root / "vendorlib" / "pkg" / "real_file.py").write_text("# real\n", encoding="utf-8")

        (round_dir2 / "reviews" / "exemptions.md").write_text(
            "Regex/glob spans must not be treated as path citations:\n"
            "- `^_?\\s*(no|none)\\b.*declared.*_?$`\n"
            "- `__pycache__/*.pyc`\n"
            "\n"
            "Bare-domain URLs must not be treated as path citations:\n"
            "- `docs.python.org/3/library/os.html`\n"
            "- `github.com/org/repo/blob/main/src/foo.py`\n"
            "\n"
            "Submodule-relative citation, resolves against the vendorlib submodule root:\n"
            "- `pkg/real_file.py`\n"
            "\n"
            "Submodule-relative citation to a file that genuinely does not exist "
            "(submodule bases must not blanket-exempt everything):\n"
            "- `pkg/does_not_exist_in_submodule.py`\n"
            "\n"
            "<!-- verify:ignore -->\n"
            "Explicitly ignored line citing `totally/made/up/ignored_prev_line.py`\n"
            "Explicitly ignored same-line citation `totally/made/up/ignored_same_line.py` <!-- verify:ignore -->\n"
            "\n"
            "A genuinely dangling citation with none of the above properties, must still fail:\n"
            "- `docs/genuinely_missing_file.md`\n",
            encoding="utf-8",
        )

        violations, _coverage = verify_protocol.verify_project(exempt_root)
        details = " | ".join(v["detail"] for v in violations)

        check(
            "declared.*_?$" not in details and "__pycache__/*.pyc" not in details,
            "verify exempts regex/glob-metacharacter spans from citation checking",
        )
        check(
            "docs.python.org" not in details and "github.com/org/repo" not in details,
            "verify exempts bare-domain URL spans from citation checking",
        )
        check(
            "pkg/real_file.py" not in details,
            "verify resolves a citation relative to a first-level git submodule root",
        )
        check(
            any("pkg/does_not_exist_in_submodule.py" in v["detail"] for v in violations),
            "verify still catches a dangling citation inside a submodule-relative path",
        )
        check(
            "ignored_prev_line.py" not in details and "ignored_same_line.py" not in details,
            "verify:ignore marker (same line or line immediately above) suppresses citation checking",
        )
        check(
            any("genuinely_missing_file.md" in v["detail"] for v in violations),
            "verify still catches a genuinely dangling citation with no applicable exemption (no false negative)",
        )
    finally:
        shutil.rmtree(exempt_root, ignore_errors=True)

    # Rule B "bases missing <project>/.harnessloop/" fixture (TH-0007): a
    # real round 2 review cited PATHISH_PREFIXES verbatim (setup/, state/)
    # and a templated goal-contract path, both of which the pre-fix bases
    # list could never resolve. Cover the fix plus a negative safeguard
    # (a genuinely missing file under .harnessloop/ must still fail).
    harnessloop_base_root = REPO_ROOT / ".tmp" / f"verify-fixture-harnessloop-base-{uuid.uuid4().hex}"
    round_dir3 = harnessloop_base_root / ".harnessloop" / "goals" / "20260103-001-fixture" / "rounds" / "0001"
    try:
        (round_dir3 / "evidence").mkdir(parents=True)
        (round_dir3 / "reviews").mkdir(parents=True)
        (round_dir3 / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )

        # Real protocol-relative files that live under <project>/.harnessloop/,
        # cited using their PATHISH_PREFIXES prefix verbatim (setup/, state/).
        (harnessloop_base_root / ".harnessloop" / "setup").mkdir(parents=True)
        (harnessloop_base_root / ".harnessloop" / "setup" / "data-sources.md").write_text("real\n", encoding="utf-8")
        (harnessloop_base_root / ".harnessloop" / "state").mkdir(parents=True)
        (harnessloop_base_root / ".harnessloop" / "state" / "self-check.md").write_text("real\n", encoding="utf-8")

        (round_dir3 / "reviews" / "harnessloop-base.md").write_text(
            "Protocol-relative citations resolve against <project>/.harnessloop/:\n"
            "- `setup/data-sources.md`\n"
            "- `state/self-check.md`\n"
            "\n"
            "A genuinely missing file under .harnessloop/ must still fail "
            "(the added base must not blanket-exempt everything):\n"
            "- `state/does-not-exist-under-harnessloop.md`\n"
            "\n"
            "Templated/placeholder path must not be treated as a citation:\n"
            "- `goals/<id>/data-contract.md`\n",
            encoding="utf-8",
        )

        violations, _coverage = verify_protocol.verify_project(harnessloop_base_root)
        details = " | ".join(v["detail"] for v in violations)

        check(
            "setup/data-sources.md" not in details and "state/self-check.md" not in details,
            "verify resolves a PATHISH_PREFIXES-verbatim citation against <project>/.harnessloop/",
        )
        check(
            any("does-not-exist-under-harnessloop.md" in v["detail"] for v in violations),
            "verify still catches a genuinely dangling citation under .harnessloop/ (no false negative)",
        )
        check(
            "data-contract.md" not in details,
            "verify exempts a templated path with an angle-bracket placeholder from citation checking",
        )
    finally:
        shutil.rmtree(harnessloop_base_root, ignore_errors=True)

    # TH-0008 (Rule B dangling-citation false-positive reduction): unit-level
    # teeth on the pure helper functions first, then an end-to-end round
    # fixture covering the same ground through the real verify_project path.
    # A live 62-file .hopper/handoffs/ corpus put dangling-citation
    # false-positives at 532/1054 (50%); this suite is the falsifiable half
    # of the fix -- every assertion here must independently break if any one
    # of the five changes (locator-suffix stripping, nested-submodule bases,
    # suffix-unique fallback, ~//abs exemption) is reverted.
    print("  TH-0008: Rule B false-positive reduction")

    # -- strip_locator_suffix: unit teeth --
    check(
        verify_protocol.strip_locator_suffix("plugins/foo/scripts/check_setup.py:123") == "plugins/foo/scripts/check_setup.py",
        "strip_locator_suffix strips a trailing :<line>",
    )
    check(
        verify_protocol.strip_locator_suffix("docs/x.md:10-20") == "docs/x.md",
        "strip_locator_suffix strips a trailing :<start>-<end> line range",
    )
    check(
        verify_protocol.strip_locator_suffix(".hopper/tasks/code-review-adversarial.md::root") == ".hopper/tasks/code-review-adversarial.md",
        "strip_locator_suffix strips a trailing ::<anchor>",
    )
    check(
        verify_protocol.strip_locator_suffix("plugins/foo/bar.py") == "plugins/foo/bar.py",
        "strip_locator_suffix leaves a locator-free path unchanged",
    )

    # PR-1 (external-citation-base-spec-20260727.md §5): LINE_SUFFIX_RE extended
    # to a comma-separated multi-range locator, e.g. `:44-46,443-507`. The four
    # checks above (single :<line>, :<start>-<end>, ::<anchor>, locator-free) are
    # re-asserted unchanged immediately above this block -- this is a strict
    # regex superset, not a replacement shape.
    check(
        verify_protocol.strip_locator_suffix(
            "app/kernel-client/swift/X.swift:44-46,443-507"
        )
        == "app/kernel-client/swift/X.swift",
        "strip_locator_suffix (PR-1) strips a comma-separated multi-range locator",
    )
    check(
        verify_protocol.strip_locator_suffix(
            "app/kernel-client/swift/X.swift:1,44-46,443-507,900"
        )
        == "app/kernel-client/swift/X.swift",
        "strip_locator_suffix (PR-1) strips a 4-segment mix of bare lines and ranges",
    )

    # -- suffix_unique_match: unit teeth (segment comparison, >=2 segments, uniqueness,
    # and TH-0008 REWORK: match-time re-verification + trailing-slash directory semantics) --
    # Real files on disk this time (not a hand-built fake index) -- suffix_unique_match
    # now re-checks the specific matched path against the filesystem, so a fixture index
    # entry that names nothing real would silently make every "must resolve" assertion
    # below meaningless.
    suffix_root = REPO_ROOT / ".tmp" / f"verify-fixture-suffixindex-{uuid.uuid4().hex}"
    try:
        (suffix_root / "plugins" / "harnessloop" / "skills" / "harnessloop-setup").mkdir(parents=True)
        (suffix_root / "plugins" / "harnessloop" / "skills" / "harnessloop-setup" / "SKILL.md").write_text(
            "# skill\n", encoding="utf-8"
        )
        (suffix_root / "app" / "docs").mkdir(parents=True)
        (suffix_root / "app" / "docs" / "macos.html").write_text("<html></html>\n", encoding="utf-8")
        (suffix_root / "docs" / "guide").mkdir(parents=True)
        (suffix_root / "docs" / "guide" / "setup.md").write_text("# setup\n", encoding="utf-8")
        (suffix_root / "other" / "guide").mkdir(parents=True)
        (suffix_root / "other" / "guide" / "setup.md").write_text("# setup\n", encoding="utf-8")
        (suffix_root / "deep" / "pkg").mkdir(parents=True)
        (suffix_root / "deep" / "pkg" / "real.md").write_text("real\n", encoding="utf-8")

        unique_index = verify_protocol.build_suffix_index(suffix_root)
        check(
            verify_protocol.suffix_unique_match("harnessloop-setup/SKILL.md", unique_index, suffix_root) is True,
            "suffix_unique_match accepts a unique multi-segment suffix hit (TH-0008 original case)",
        )
        check(
            verify_protocol.suffix_unique_match("SKILL.md", unique_index, suffix_root) is False,
            "suffix_unique_match rejects a single (bare) segment even when the basename is indexed (false-negative guard: typo-prone, no context)",
        )
        check(
            verify_protocol.suffix_unique_match("harnessloop-setup/SKIL.md", unique_index, suffix_root) is False,
            "suffix_unique_match rejects a typo'd basename with zero index hits (false-negative guard)",
        )
        check(
            verify_protocol.suffix_unique_match("component/os.html", unique_index, suffix_root) is False,
            "suffix_unique_match does not let `os.html` match `.../macos.html` (segment comparison, not string endswith)",
        )
        check(
            verify_protocol.suffix_unique_match("guide/setup.md", unique_index, suffix_root) is False,
            "suffix_unique_match rejects an ambiguous suffix matching >=2 real files (false-negative guard: no false exemption from ambiguity)",
        )

        # TH-0008 REWORK counterexample 1/5: trailing_slash_file. A citation ending in
        # `/` names a directory; `pkg/real.md/` must not resolve against the *file*
        # `pkg/real.md` merely because the trailing slash was discarded by segment-splitting.
        # codex T-062 repro: dangling_count=0 pre-fix; must be >=1 (i.e. no match) post-fix.
        check(
            verify_protocol.suffix_unique_match("pkg/real.md/", unique_index, suffix_root) is False,
            "suffix_unique_match honors trailing-slash directory semantics: a file must not "
            "satisfy a directory-shaped citation (TH-0008 REWORK: trailing_slash_file, "
            "codex T-062)",
        )
        # Mutation check: with the trailing-slash guard removed (i.e. calling
        # `_exists_as` unconditionally with want_dir=False, as the pre-REWORK code did),
        # this same citation *does* resolve -- confirming the assertion above has teeth.
        check(
            verify_protocol._exists_as(suffix_root / "deep" / "pkg" / "real.md", False) is True,
            "mutation control: without directory-semantics enforcement the same path would "
            "wrongly resolve (proves the guard above is load-bearing, not vacuous)",
        )

        # TH-0008 REWORK counterexample 2/5: stale_index_after_delete. Build the index,
        # delete the file it recorded, then confirm suffix_unique_match no longer trusts
        # the (now stale) index entry. codex T-062 repro: match_after_delete=True,
        # target_exists=False pre-fix; must be False post-fix.
        gone = suffix_root / "deep" / "pkg" / "gone.md"
        gone.write_text("will be deleted\n", encoding="utf-8")
        stale_index = verify_protocol.build_suffix_index(suffix_root)
        check(
            verify_protocol.suffix_unique_match("pkg/gone.md", stale_index, suffix_root) is True,
            "sanity: suffix_unique_match matches pkg/gone.md while it still exists",
        )
        gone.unlink()
        check(
            verify_protocol.suffix_unique_match("pkg/gone.md", stale_index, suffix_root) is False,
            "suffix_unique_match re-verifies existence at match time and rejects a stale "
            "index entry for a since-deleted file (TH-0008 REWORK: stale_index_after_delete, "
            "codex T-062)",
        )
        # Mutation check: the index itself still (wrongly, if untrusted) records the
        # deleted file as if it were real -- proving the re-verification, not index
        # rebuilding, is what makes the assertion above pass.
        check(
            ("pkg", "gone.md")[-1] in stale_index and any(
                c[-2:] == ("pkg", "gone.md") for c in stale_index.get("gone.md", [])
            ),
            "mutation control: the stale index still lists the deleted file (proves "
            "suffix_unique_match's own re-check, not a rebuilt index, catches the staleness)",
        )

        # TH-0008 REWORK counterexample 3/5: broken_symlink. os.walk() lists a symlink in
        # `filenames` regardless of whether its target exists; without a match-time
        # existence check a broken symlink is indexed exactly like a real file. codex
        # T-062 repro: dangling_count=0 pre-fix; must be >=1 post-fix. This exercises the
        # walk-based fallback specifically, so it is built and indexed on a non-git
        # directory (a nested subdirectory of this fixture, still not its own git
        # toplevel, so build_suffix_index falls back to the walk).
        try:
            (suffix_root / "deep" / "pkg" / "broken.md").symlink_to("missing-target.md")
            symlinks_supported = True
        except (OSError, NotImplementedError):
            symlinks_supported = False
        if symlinks_supported:
            symlink_index = verify_protocol.build_suffix_index(suffix_root)
            check(
                verify_protocol.suffix_unique_match("pkg/broken.md", symlink_index, suffix_root) is False,
                "suffix_unique_match re-verifies existence at match time and rejects a "
                "broken symlink that os.walk indexed without following "
                "(TH-0008 REWORK: broken_symlink, codex T-062)",
            )
            # Mutation check: the symlink is genuinely indexed (walk-based index has an
            # entry for it) -- proving the rejection above comes from the match-time
            # existence re-check, not from the symlink being absent from the index.
            check(
                any(c[-2:] == ("pkg", "broken.md") for c in symlink_index.get("broken.md", [])),
                "mutation control: os.walk indexes the broken symlink like a real file "
                "(proves the rejection above is the match-time re-check doing the work)",
            )
        else:
            print("  (skipped: symlinks unsupported on this filesystem -- broken_symlink counterexample)")
    finally:
        shutil.rmtree(suffix_root, ignore_errors=True)

    # -- _looks_like_out_of_project / pathish_citations: ~/, POSIX-absolute, and
    # Windows-absolute exemption, now counted via citations_exempt_external --
    home_and_abs_text = (
        "External design wiki, home-relative, out of project scope:\n"
        "- `~/.llm-wiki/agent-app-design/kernel/kernel-ecosystem-facts.md`\n"
        "\n"
        "Filesystem-absolute, out of project scope:\n"
        "- `/etc/hosts`\n"
        "\n"
        "Windows drive-absolute, out of project scope:\n"
        "- `C:/Users/x/file.py`\n"
        "\n"
        "Windows drive-absolute (backslash form before normalization), out of project scope:\n"
        "- `C:\\Users\\x\\other.py`\n"
        "\n"
        "UNC path, out of project scope:\n"
        "- `\\\\server\\share\\doc.md`\n"
    )
    (
        cited_home_abs,
        exempt_external_count,
        ignored_explicit_count,
        shape_dropped_count,
        has_ignore_marker,
    ) = verify_protocol.pathish_citations(home_and_abs_text)
    check(
        cited_home_abs == [],
        "pathish_citations extracts none of ~/ home-relative, /-absolute, C:/-absolute, "
        "or UNC spans as a citation",
    )
    check(
        exempt_external_count == 5,
        f"pathish_citations counts every out-of-project span in citations_exempt_external "
        f"(got {exempt_external_count}, expected 5)",
    )
    check(
        ignored_explicit_count == 0 and shape_dropped_count == 0 and has_ignore_marker is False,
        "pathish_citations: a text with no verify:ignore marker and no shape-dropped span "
        f"reports all three new PR-0 fields as zero/false (got ignored={ignored_explicit_count}, "
        f"shape_dropped={shape_dropped_count}, has_ignore_marker={has_ignore_marker})",
    )

    # PR-0 (external-citation-base-spec-20260727.md §5, G-teeth "delete any counter
    # -> fixture red"): precise-count fixtures for the three new coverage fields.
    # citations_ignored_explicit / review_files_with_ignore close the "ignore-marker
    # misuse is unmonitorable" gap (T-066 §1 judgment criterion 2); citations_shape_dropped
    # closes the "delete the extension to go green" gap. Each assertion below is only
    # satisfiable if the corresponding counter increment is present and wired through
    # verify_round into `coverage` -- delete any one of the three increments in
    # verify_protocol.py and the matching check here goes red.
    print("  PR-0: citations_ignored_explicit / review_files_with_ignore / citations_shape_dropped")
    pr0_ignore_shape_text = (
        "Shape-dropped spans -- contain a slash but no extension, no trailing "
        "slash, no dot-dot segment:\n"
        "- `src/pkgdir`\n"
        "- `@@wiki/kernel`\n"
        "\n"
        "Not shape-dropped -- has a file extension, still a real citation:\n"
        "- `docs/genuinely_missing_file.md`\n"
        "\n"
        "<!-- verify:ignore -->\n"
        "Ignored line citing `totally/made/up/ignored_prev_line.py` and a second "
        "span on the same ignored line `another/ignored/span.py`\n"
        "Ignored same-line citation `totally/made/up/ignored_same_line.py` <!-- verify:ignore -->\n"
    )
    (
        pr0_cited,
        pr0_exempt_external,
        pr0_ignored_explicit,
        pr0_shape_dropped,
        pr0_has_ignore,
    ) = verify_protocol.pathish_citations(pr0_ignore_shape_text)
    check(
        pr0_shape_dropped == 2,
        f"citations_shape_dropped counts exactly the 2 extensionless, non-trailing-slash, "
        f"no-'..' spans (got {pr0_shape_dropped}, expected 2)",
    )
    check(
        pr0_ignored_explicit == 3,
        "citations_ignored_explicit counts every backtick span on a verify:ignore-exempted "
        "line: 2 (two spans on the prev-line-marker-exempted line) + 1 (one span on the "
        f"same-line-marker line) = 3 (got {pr0_ignored_explicit})",
    )
    check(
        pr0_has_ignore is True,
        "pathish_citations reports has_ignore_marker=True for a file containing "
        "<!-- verify:ignore --> (feeds review_files_with_ignore)",
    )
    check(
        pr0_cited == ["docs/genuinely_missing_file.md"],
        "shape-dropped and ignored spans are excluded from `cited`; the one genuine, "
        f"non-ignored, extensioned span is still checked (got {pr0_cited})",
    )

    # End-to-end round fixture: same text as a real reviews/*.md file, confirming
    # verify_round/verify_project wire ignored_explicit/shape_dropped/has_ignore
    # through into the module's `coverage` dict (not just the pure-helper values above).
    pr0_root = REPO_ROOT / ".tmp" / f"verify-fixture-pr0-{uuid.uuid4().hex}"
    pr0_round_dir = pr0_root / ".harnessloop" / "goals" / "20260106-001-fixture" / "rounds" / "0001"
    try:
        (pr0_round_dir / "evidence").mkdir(parents=True)
        (pr0_round_dir / "reviews").mkdir(parents=True)
        (pr0_round_dir / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (pr0_round_dir / "reviews" / "pr0.md").write_text(pr0_ignore_shape_text, encoding="utf-8")
        pr0_violations, pr0_coverage = verify_protocol.verify_project(pr0_root)
        check(
            pr0_coverage.get("citations_shape_dropped") == 2,
            f"verify_project's coverage.citations_shape_dropped == 2 (got {pr0_coverage.get('citations_shape_dropped')})",
        )
        check(
            pr0_coverage.get("citations_ignored_explicit") == 3,
            f"verify_project's coverage.citations_ignored_explicit == 3 (got {pr0_coverage.get('citations_ignored_explicit')})",
        )
        check(
            pr0_coverage.get("review_files_with_ignore") == 1,
            f"verify_project's coverage.review_files_with_ignore == 1 for the one review "
            f"file carrying the marker (got {pr0_coverage.get('review_files_with_ignore')})",
        )
        check(
            any("docs/genuinely_missing_file.md" in v["detail"] for v in pr0_violations),
            "the one genuine, non-ignored, non-shape-dropped citation is still reported "
            "dangling-citation (no false negative introduced by the new counters)",
        )
        check(
            not any("ignored_prev_line.py" in v["detail"] or "ignored_same_line.py" in v["detail"] for v in pr0_violations),
            "ignored spans still never produce a dangling-citation violation",
        )
        check(
            not any("src/pkgdir" in v["detail"] or "@@wiki/kernel" in v["detail"] for v in pr0_violations),
            "shape-dropped spans still never produce a dangling-citation violation "
            "(they never entered `cited` at all -- unchanged pre-existing behavior)",
        )
    finally:
        shutil.rmtree(pr0_root, ignore_errors=True)

    # -- end-to-end round fixture: locators, nested submodule, suffix fallback, ~//abs exemption --
    th0008_root = REPO_ROOT / ".tmp" / f"verify-fixture-th0008-{uuid.uuid4().hex}"
    round_dir4 = th0008_root / ".harnessloop" / "goals" / "20260105-001-fixture" / "rounds" / "0001"
    try:
        (round_dir4 / "evidence" / "runtime").mkdir(parents=True)
        (round_dir4 / "reviews").mkdir(parents=True)
        (round_dir4 / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (round_dir4 / "evidence" / "runtime" / "real.md").write_text("real\n", encoding="utf-8")

        # Nested submodule (TH-0008: submodule_roots() previously only
        # honored top-level .gitmodules path= entries; kernels/openclaw and
        # kernels/hermes in this very repo are two-segment paths).
        (th0008_root / ".gitmodules").write_text(
            '[submodule "kernels/vendorlib"]\n'
            "\tpath = kernels/vendorlib\n"
            "\turl = https://example.invalid/vendorlib.git\n",
            encoding="utf-8",
        )
        (th0008_root / "kernels" / "vendorlib" / "pkg").mkdir(parents=True)
        (th0008_root / "kernels" / "vendorlib" / "pkg" / "real_file.py").write_text("# real\n", encoding="utf-8")
        # Decoy sharing the cited suffix's last two segments (`pkg/real_file.py`)
        # so the suffix-unique fallback sees *two* hits (ambiguous -> False) and
        # cannot rescue this citation on its own. This isolates the assertion
        # below to submodule_roots()'s nested-path handling specifically --
        # without the decoy, the suffix fallback alone would resolve
        # `pkg/real_file.py` even if the nested-submodule fix regressed.
        (th0008_root / "decoy" / "pkg").mkdir(parents=True)
        (th0008_root / "decoy" / "pkg" / "real_file.py").write_text("# decoy\n", encoding="utf-8")

        # Suffix-unique fallback target, mirroring the actual TH-0008 case:
        # harnessloop-setup/SKILL.md really lives several segments deeper.
        (th0008_root / "plugins" / "harnessloop" / "skills" / "harnessloop-setup").mkdir(parents=True)
        (th0008_root / "plugins" / "harnessloop" / "skills" / "harnessloop-setup" / "SKILL.md").write_text(
            "# skill\n", encoding="utf-8"
        )
        # openai.yaml under harnessloop-setup/agents/ -- the other TH-0008 original example.
        (th0008_root / "plugins" / "harnessloop" / "skills" / "harnessloop-setup" / "agents").mkdir()
        (th0008_root / "plugins" / "harnessloop" / "skills" / "harnessloop-setup" / "agents" / "openai.yaml").write_text(
            "name: openai\n", encoding="utf-8"
        )

        (round_dir4 / "reviews" / "th0008.md").write_text(
            "Locator suffix, real file, must resolve:\n"
            "- `rounds/0001/evidence/runtime/real.md:42`\n"
            "- `rounds/0001/evidence/runtime/real.md:10-20`\n"
            "\n"
            "Locator suffix on a file that genuinely does not exist -- must still fail "
            "(locator-stripping must not blanket-exempt everything):\n"
            "- `rounds/0001/evidence/runtime/does-not-exist.md:999`\n"
            "\n"
            "Nested-submodule-relative citation, resolves against kernels/vendorlib:\n"
            "- `pkg/real_file.py`\n"
            "\n"
            "Suffix-unique fallback (TH-0008 original targets):\n"
            "- `harnessloop-setup/SKILL.md`\n"
            "- `harnessloop-setup/agents/openai.yaml`\n"
            "\n"
            "Single-segment bare filename must still fail even though the fallback would "
            "otherwise find it (false-negative guard: no project-relative context):\n"
            "- `agents/`\n"
            "\n"
            "Typo'd suffix must still fail (false-negative guard):\n"
            "- `harnessloop-setup/SKIILL.md`\n"
            "\n"
            "Home-relative and absolute citations, out of project scope, exempt:\n"
            "- `~/.llm-wiki/agent-app-design/kernel/kernel-ecosystem-facts.md`\n"
            "- `/etc/hosts`\n",
            encoding="utf-8",
        )

        violations, coverage = verify_protocol.verify_project(th0008_root)
        details = " | ".join(v["detail"] for v in violations)

        check(
            "real.md" not in details,
            "verify resolves a real.md citation carrying a :<line> or :<start>-<end> locator suffix",
        )
        check(
            any("does-not-exist.md" in v["detail"] for v in violations),
            "verify still catches a dangling citation even with a numeric locator suffix (no false negative)",
        )
        check(
            "pkg/real_file.py" not in details,
            "verify resolves a citation relative to a nested (multi-segment) git submodule root",
        )
        # T-064 downgrade (user-confirmed 2026-07-26): the suffix-unique fallback no
        # longer turns a dangling citation into a pass -- these two citations (the
        # ORIGINAL TH-0008 suffix-fallback motivating examples) now MUST be reported
        # dangling, each carrying a display-only hint pointing at its unique suffix
        # match, and each must tick citations_suffix_hinted. This assertion is the
        # literal flip of what TH-0008 required and what this same fixture asserted
        # before T-064 -- the flip itself is the strongest evidence the downgrade is
        # real, not just a docstring claim.
        skill_violation = next(
            (v for v in violations if "harnessloop-setup/SKILL.md" in v["detail"] and "openai.yaml" not in v["detail"]),
            None,
        )
        yaml_violation = next(
            (v for v in violations if "harnessloop-setup/agents/openai.yaml" in v["detail"]),
            None,
        )
        check(
            skill_violation is not None and yaml_violation is not None,
            "T-064: the TH-0008 original suffix-unique citations (harnessloop-setup/SKILL.md, "
            "harnessloop-setup/agents/openai.yaml) are now reported dangling instead of "
            "resolved (suffix match no longer passes a citation)",
        )
        check(
            skill_violation is not None
            and "a unique suffix match exists at plugins/harnessloop/skills/harnessloop-setup/SKILL.md" in skill_violation["detail"]
            and "verify:ignore" in skill_violation["detail"],
            f"T-064: the dangling harnessloop-setup/SKILL.md violation carries a suffix hint "
            f"pointing at the real match and the verify:ignore escape hatch (got: {skill_violation})",
        )
        check(
            yaml_violation is not None
            and "a unique suffix match exists at plugins/harnessloop/skills/harnessloop-setup/agents/openai.yaml" in yaml_violation["detail"],
            f"T-064: the dangling harnessloop-setup/agents/openai.yaml violation carries a "
            f"suffix hint pointing at the real match (got: {yaml_violation})",
        )
        check(
            coverage.get("citations_suffix_hinted") == 2,
            "T-064: citations_suffix_hinted counts exactly the 2 hinted dangling citations "
            f"in this fixture (got {coverage.get('citations_suffix_hinted')})",
        )
        check(
            any("`agents/`" in v["detail"] for v in violations),
            "verify still flags a single-segment (bare) citation as dangling even though a longer suffix would match (false-negative guard)",
        )
        check(
            any("SKIILL.md" in v["detail"] for v in violations),
            "verify still flags a typo'd suffix citation as dangling (false-negative guard)",
        )
        check(
            "kernel-ecosystem-facts.md" not in details and "/etc/hosts" not in details,
            "verify exempts ~/ home-relative and /-absolute citations instead of resolving (and failing) them literally",
        )
    finally:
        shutil.rmtree(th0008_root, ignore_errors=True)

    # PR-1 (external-citation-base-spec-20260727.md §5): end-to-end round
    # fixture for the comma-separated multi-range locator. Positive: after
    # stripping `:44-46,443-507`, the bare path resolves to a real file ->
    # not dangling. Negative: the same locator shape on a path that does not
    # exist -> still dangling-citation (the locator strip must never
    # manufacture a false pass on a genuinely missing file).
    print("  PR-1: comma-separated multi-range locator (:44-46,443-507)")
    multirange_root = REPO_ROOT / ".tmp" / f"verify-fixture-multirange-{uuid.uuid4().hex}"
    round_dir_mr = multirange_root / ".harnessloop" / "goals" / "20260107-001-fixture" / "rounds" / "0001"
    try:
        (round_dir_mr / "evidence").mkdir(parents=True)
        (round_dir_mr / "reviews").mkdir(parents=True)
        (round_dir_mr / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (multirange_root / "app" / "kernel-client" / "swift").mkdir(parents=True)
        (multirange_root / "app" / "kernel-client" / "swift" / "X.swift").write_text(
            "// real swift file\n" * 600, encoding="utf-8"
        )
        (round_dir_mr / "reviews" / "multirange.md").write_text(
            "Multi-range locator on a real file, must resolve (not dangling):\n"
            "- `app/kernel-client/swift/X.swift:44-46,443-507`\n"
            "\n"
            "Multi-range locator on a file that does not exist, must stay dangling:\n"
            "- `app/kernel-client/swift/DoesNotExist.swift:1-2,10-20`\n",
            encoding="utf-8",
        )
        violations, _coverage = verify_protocol.verify_project(multirange_root)
        details = " | ".join(v["detail"] for v in violations)
        check(
            "kernel-client/swift/X.swift:44-46,443-507" not in details,
            "PR-1: a multi-range-locator citation on a real file resolves (not dangling)",
        )
        check(
            any("DoesNotExist.swift" in v["detail"] for v in violations),
            "PR-1: a multi-range-locator citation on a nonexistent file still reports dangling-citation",
        )
    finally:
        shutil.rmtree(multirange_root, ignore_errors=True)

    # TH-0008 REWORK counterexample 4/5: noise_pruned_ambiguity. Two real files
    # share the cited suffix's last two segments -- one under an ordinary source
    # directory (`src/`), one under a directory that happens to share a name with a
    # NOISE_DIR_NAMES entry (`build/`) but is genuinely tracked source here. The
    # pre-REWORK walk-based index pruned `build/` unconditionally, making
    # `src/pkg/real.md` look like the *only* candidate -- a false uniqueness born
    # from a hardcoded denylist with no protocol basis. codex T-062 repro:
    # dangling_count=0 pre-fix; must be >=1 post-fix (git-tracked index sees both).
    noise_root = REPO_ROOT / ".tmp" / f"verify-fixture-noise-{uuid.uuid4().hex}"
    round_dir5 = noise_root / ".harnessloop" / "goals" / "20260106-001-fixture" / "rounds" / "0001"
    try:
        (round_dir5 / "evidence").mkdir(parents=True)
        (round_dir5 / "reviews").mkdir(parents=True)
        (round_dir5 / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (noise_root / "src" / "pkg").mkdir(parents=True)
        (noise_root / "src" / "pkg" / "real.md").write_text("src real\n", encoding="utf-8")
        (noise_root / "build" / "pkg").mkdir(parents=True)
        (noise_root / "build" / "pkg" / "real.md").write_text("build real\n", encoding="utf-8")

        (round_dir5 / "reviews" / "noise.md").write_text(
            "Ambiguous suffix -- two real, git-tracked files share this suffix "
            "(src/pkg/real.md and build/pkg/real.md), must NOT resolve:\n"
            "- `pkg/real.md`\n",
            encoding="utf-8",
        )

        # Make this fixture its own git working-tree root so build_suffix_index takes
        # the git-tracked-file path instead of the walk-based (NOISE_DIR_NAMES-pruning)
        # fallback -- see build_suffix_index / _git_tracked_index docstrings. `git add`
        # (not `commit`) is enough for `git ls-files` and needs no configured identity.
        git_available = shutil.which("git") is not None
        if git_available:
            init = subprocess.run(["git", "init", "-q"], cwd=noise_root, capture_output=True)
            add = subprocess.run(["git", "add", "-A"], cwd=noise_root, capture_output=True)
            git_available = init.returncode == 0 and add.returncode == 0

        if git_available:
            violations, _coverage = verify_protocol.verify_project(noise_root)
            check(
                any("pkg/real.md" in v["detail"] for v in violations),
                "verify (git-tracked index) reports the ambiguous `pkg/real.md` suffix as "
                "dangling instead of resolving it via a noise-pruning false-uniqueness "
                "(TH-0008 REWORK: noise_pruned_ambiguity, codex T-062)",
            )

            # Mutation control: reproduce the pre-REWORK walk-based index (NOISE_DIR_NAMES
            # pruning, no git) directly and confirm it *would* have seen only one
            # candidate -- proving the git-tracked-index switch, not something else, is
            # what makes the assertion above hold.
            pruned_index: dict[str, list[tuple]] = {}
            for dirpath, dirnames, filenames in os.walk(noise_root):
                dirnames[:] = [d for d in dirnames if d not in verify_protocol.NOISE_DIR_NAMES]
                rel_dir = Path(dirpath).relative_to(noise_root)
                dir_parts = () if str(rel_dir) == "." else rel_dir.parts
                for filename in filenames:
                    pruned_index.setdefault(filename, []).append(dir_parts + (filename,))
            pruned_matches = [
                c for c in pruned_index.get("real.md", [])
                if len(c) >= 2 and c[-2:] == ("pkg", "real.md")
            ]
            check(
                len(pruned_matches) == 1,
                "mutation control: the walk-based NOISE_DIR_NAMES-pruned index sees only "
                "one `pkg/real.md` candidate (proves the git-tracked-index switch, not "
                "existence re-checking, is what surfaces this ambiguity)",
            )
        else:
            print("  (skipped: git unavailable -- noise_pruned_ambiguity counterexample)")
    finally:
        shutil.rmtree(noise_root, ignore_errors=True)

    # TH-0008 REWORK counterexample 5/5: submodule_parent_escape. A `.gitmodules`
    # `path =` entry pointing outside the project root (`../outside`) must not become
    # a citation resolution base, even though the sibling directory genuinely exists
    # on the host filesystem. codex T-062 repro: dangling_count=0 pre-fix (the escaped
    # base let `pkg/ghost.py` resolve).
    escape_root = REPO_ROOT / ".tmp" / f"verify-fixture-escape-{uuid.uuid4().hex}"
    escape_project = escape_root / "project"
    escape_outside = escape_root / "outside"
    round_dir6 = escape_project / ".harnessloop" / "goals" / "20260107-001-fixture" / "rounds" / "0001"
    try:
        (round_dir6 / "evidence").mkdir(parents=True)
        (round_dir6 / "reviews").mkdir(parents=True)
        (round_dir6 / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (escape_outside / "pkg").mkdir(parents=True)
        (escape_outside / "pkg" / "ghost.py").write_text("# outside the project\n", encoding="utf-8")

        (escape_project / ".gitmodules").write_text(
            '[submodule "escaped"]\n\tpath = ../outside\n\turl = https://example.invalid/escaped.git\n',
            encoding="utf-8",
        )

        (round_dir6 / "reviews" / "escape.md").write_text(
            "Citation that only exists via a .gitmodules path escaping the project root, "
            "must NOT resolve:\n"
            "- `pkg/ghost.py`\n"
            "\n"
            "Citation containing a literal `../` that would walk the *project root* base "
            "itself outside the project tree, must also NOT resolve (this is the general "
            "containment check in `_resolve_in_project`, independent of submodule_roots):\n"
            "- `../outside/pkg/ghost.py`\n",
            encoding="utf-8",
        )

        roots = verify_protocol.submodule_roots(escape_project)
        check(
            all(r.resolve() != escape_outside.resolve() for r in roots),
            "submodule_roots rejects a .gitmodules `path =` entry that resolves outside "
            "the project root (TH-0008 REWORK: submodule_parent_escape containment, "
            "codex T-062)",
        )

        violations, _coverage = verify_protocol.verify_project(escape_project)
        check(
            any("pkg/ghost.py" in v["detail"] and "../outside" not in v["detail"] for v in violations),
            "verify reports `pkg/ghost.py` as dangling instead of resolving it through an "
            "escaped .gitmodules submodule base (TH-0008 REWORK: submodule_parent_escape, "
            "codex T-062)",
        )
        check(
            any("../outside/pkg/ghost.py" in v["detail"] for v in violations),
            "verify reports a literal `../`-escaping citation as dangling instead of "
            "resolving it against the project root's parent directory (TH-0008 REWORK: "
            "general containment in _resolve_in_project, codex T-062)",
        )

        # Mutation control: without containment, the escaped path still genuinely
        # holds pkg/ghost.py on disk -- proving the rejection above comes from the
        # containment check, not from the file being absent.
        check(
            (escape_project / ".." / "outside" / "pkg" / "ghost.py").resolve().is_file(),
            "mutation control: the escaped path still genuinely holds pkg/ghost.py on "
            "disk (proves containment, not absence, is what the check above relies on)",
        )
    finally:
        shutil.rmtree(escape_root, ignore_errors=True)

    print("  T-063: MUST-FIX regression guards (untracked pseudo-unique, symlink containment escape)")

    # T-063 MUST-FIX 1 counterexample: untracked_pseudo_unique. A tracked file and a
    # genuinely-existing, non-gitignored *untracked* file share the same suffix. The
    # narrowed (tracked-only) index from the prior rework made the tracked file look
    # like the *only* candidate -- a false uniqueness born from excluding real,
    # non-ignored worktree files rather than from a hardcoded denylist this time.
    # codex T-063 repro: before_add resolves (bug), after_add is dangling (accidental
    # fix-by-git-add, not by design). Post-fix must be dangling in BOTH states, since
    # the untracked file is a real, non-ignored worktree fact independent of whether
    # it has been `git add`ed yet.
    untracked_root = REPO_ROOT / ".tmp" / f"verify-fixture-untracked-{uuid.uuid4().hex}"
    round_dir7 = untracked_root / ".harnessloop" / "goals" / "20260108-001-fixture" / "rounds" / "0001"
    try:
        (round_dir7 / "evidence").mkdir(parents=True)
        (round_dir7 / "reviews").mkdir(parents=True)
        (round_dir7 / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (untracked_root / "src" / "pkg").mkdir(parents=True)
        (untracked_root / "src" / "pkg" / "real.md").write_text("tracked\n", encoding="utf-8")
        (untracked_root / "scratch" / "pkg").mkdir(parents=True)
        (untracked_root / "scratch" / "pkg" / "real.md").write_text("untracked, not ignored\n", encoding="utf-8")

        (round_dir7 / "reviews" / "untracked.md").write_text(
            "Ambiguous suffix -- one tracked file (src/pkg/real.md) and one genuinely "
            "real, non-ignored but untracked file (scratch/pkg/real.md) share this "
            "suffix, must NOT resolve:\n"
            "- `pkg/real.md`\n",
            encoding="utf-8",
        )

        git_available = shutil.which("git") is not None
        if git_available:
            init = subprocess.run(["git", "init", "-q"], cwd=untracked_root, capture_output=True)
            add_tracked = subprocess.run(
                ["git", "add", "src/pkg/real.md"], cwd=untracked_root, capture_output=True
            )
            git_available = init.returncode == 0 and add_tracked.returncode == 0

        if git_available:
            # Sanity: the tracked-only index (the prior rework's universe) sees only
            # ONE candidate for this suffix -- proving the ambiguity below is surfaced
            # by including untracked-not-ignored files, not by some other mechanism.
            tracked_only_listed = subprocess.run(
                ["git", "-C", str(untracked_root), "ls-files", "-z", "--cached", "--recurse-submodules"],
                capture_output=True,
            )
            tracked_only_index: dict[str, list[tuple]] = {}
            for raw in tracked_only_listed.stdout.split(b"\0"):
                if not raw:
                    continue
                rel = raw.decode("utf-8")
                parts = tuple(p for p in rel.split("/") if p)
                if parts:
                    tracked_only_index.setdefault(parts[-1], []).append(parts)
            tracked_only_matches = [
                c for c in tracked_only_index.get("real.md", [])
                if len(c) >= 2 and c[-2:] == ("pkg", "real.md")
            ]
            check(
                len(tracked_only_matches) == 1,
                "mutation control: a tracked-files-only index sees only one `pkg/real.md` "
                "candidate before scratch/pkg/real.md is git-added (proves the untracked/"
                "not-ignored inclusion, not something else, is what surfaces the ambiguity "
                "below; T-063 MUST-FIX 1: untracked_pseudo_unique)",
            )

            violations_before, _cov = verify_protocol.verify_project(untracked_root)
            check(
                any("pkg/real.md" in v["detail"] for v in violations_before),
                "verify reports `pkg/real.md` as dangling (multiply-resolvable) while "
                "scratch/pkg/real.md is still untracked-but-not-ignored, instead of "
                "treating the tracked file as a false-unique match (T-063 MUST-FIX 1: "
                "untracked_pseudo_unique, codex T-063)",
            )

            add_untracked = subprocess.run(
                ["git", "add", "scratch/pkg/real.md"], cwd=untracked_root, capture_output=True
            )
            if add_untracked.returncode == 0:
                violations_after, _cov = verify_protocol.verify_project(untracked_root)
                check(
                    any("pkg/real.md" in v["detail"] for v in violations_after),
                    "verify still reports `pkg/real.md` as dangling after scratch/pkg/real.md "
                    "is git-added too -- the same worktree fact must not flip the verdict "
                    "purely because of index status (no regression once both are tracked)",
                )
        else:
            print("  (skipped: git unavailable -- untracked_pseudo_unique counterexample)")
    finally:
        shutil.rmtree(untracked_root, ignore_errors=True)

    # T-063 MUST-FIX 2 counterexample: symlink_containment_escape. A project-internal
    # symlink whose *path* is inside the project but whose *target* resolves outside
    # it. Lexical `os.path.normpath` containment alone passes all three resolution
    # paths (direct base, .gitmodules base, suffix-index hit); canonical
    # (`Path.resolve`) containment on both sides must reject all three.
    if hasattr(os, "symlink"):
        symlink_root = REPO_ROOT / ".tmp" / f"verify-fixture-symlink-{uuid.uuid4().hex}"
        symlink_project = symlink_root / "project"
        symlink_outside = symlink_root / "outside"
        round_dir8 = symlink_project / ".harnessloop" / "goals" / "20260109-001-fixture" / "rounds" / "0001"
        try:
            (round_dir8 / "evidence").mkdir(parents=True)
            (round_dir8 / "reviews").mkdir(parents=True)
            (round_dir8 / "scope-lock.md").write_text(
                "# Scope Lock\n\n## Allowed Changes\n\n"
                "- Write evidence under `rounds/0001/evidence/`.\n"
                "- Write reviews under `rounds/0001/reviews/`.\n",
                encoding="utf-8",
            )
            (symlink_outside / "pkg").mkdir(parents=True)
            (symlink_outside / "pkg" / "ghost.py").write_text("# outside the project\n", encoding="utf-8")
            (symlink_outside / "pkg" / "external.md").write_text("# outside the project\n", encoding="utf-8")

            symlinks_supported = True
            try:
                (symlink_project / "link").symlink_to(symlink_outside, target_is_directory=True)
                (symlink_project / "deep" / "pkg").mkdir(parents=True)
                (symlink_project / "deep" / "pkg" / "external.md").symlink_to(
                    symlink_outside / "pkg" / "external.md"
                )
            except (OSError, NotImplementedError):
                symlinks_supported = False

            if symlinks_supported:
                (symlink_project / ".gitmodules").write_text(
                    '[submodule "x"]\n\tpath = link\n\turl = https://example.invalid/x.git\n',
                    encoding="utf-8",
                )
                (round_dir8 / "reviews" / "symlink.md").write_text(
                    "Direct base: project-internal symlink `link` points outside the project, "
                    "must NOT resolve:\n"
                    "- `link/pkg/ghost.py`\n"
                    "\n"
                    ".gitmodules base: `path = link` names the same escaping symlink, must "
                    "also NOT resolve:\n"
                    "- `pkg/ghost.py`\n"
                    "\n"
                    "Suffix fallback: a project-internal *file* symlink whose target lives "
                    "outside the project, must NOT resolve:\n"
                    "- `pkg/external.md`\n",
                    encoding="utf-8",
                )

                git_available = shutil.which("git") is not None
                if git_available:
                    init = subprocess.run(["git", "init", "-q"], cwd=symlink_project, capture_output=True)
                    add = subprocess.run(["git", "add", "-A"], cwd=symlink_project, capture_output=True)
                    git_available = init.returncode == 0 and add.returncode == 0

                if git_available:
                    # -- direct base (1/3) --
                    escaping_candidate = Path(
                        os.path.normpath(str(symlink_project / "link/pkg/ghost.py"))
                    )
                    check(
                        verify_protocol.is_under(escaping_candidate, symlink_project),
                        "mutation control: lexical normpath containment alone WOULD accept "
                        "`link/pkg/ghost.py` (its path is inside the project) -- proves the "
                        "rejection below comes from canonical resolution, not lexical "
                        "normpath (T-063 MUST-FIX 2: symlink_containment_escape, direct base)",
                    )
                    check(
                        verify_protocol._resolve_in_project(
                            symlink_project, "link/pkg/ghost.py", symlink_project
                        )
                        is None,
                        "_resolve_in_project rejects a citation resolving through a "
                        "project-internal symlink whose target is outside the project "
                        "(T-063 MUST-FIX 2: symlink_containment_escape, direct base)",
                    )

                    # -- .gitmodules base (2/3) --
                    roots = verify_protocol.submodule_roots(symlink_project)
                    check(
                        all(
                            verify_protocol._canonical(r) != verify_protocol._canonical(symlink_outside)
                            for r in roots
                        ),
                        "submodule_roots rejects a `.gitmodules` `path =` entry naming a "
                        "project-internal symlink whose target is outside the project "
                        "(T-063 MUST-FIX 2: symlink_containment_escape, .gitmodules base)",
                    )

                    # -- suffix fallback (3/3) --
                    symlink_index = verify_protocol.build_suffix_index(symlink_project)
                    escaping_match_path = symlink_project / "deep" / "pkg" / "external.md"
                    check(
                        verify_protocol.is_under(escaping_match_path, symlink_project),
                        "mutation control: lexical normpath containment alone WOULD accept "
                        "the suffix-index hit `deep/pkg/external.md` (its path is inside the "
                        "project) -- proves the rejection below comes from canonical "
                        "resolution (T-063 MUST-FIX 2: symlink_containment_escape, suffix "
                        "fallback)",
                    )
                    check(
                        verify_protocol.suffix_unique_match("pkg/external.md", symlink_index, symlink_project)
                        is False,
                        "suffix_unique_match rejects a unique suffix hit whose indexed file "
                        "is a project-internal symlink pointing outside the project "
                        "(T-063 MUST-FIX 2: symlink_containment_escape, suffix fallback)",
                    )

                    # -- end-to-end: all three citations dangling --
                    violations, _cov = verify_protocol.verify_project(symlink_project)
                    details = " | ".join(v["detail"] for v in violations)
                    check(
                        "link/pkg/ghost.py" in details,
                        "verify reports `link/pkg/ghost.py` as dangling instead of resolving "
                        "it through an escaping project-internal symlink base "
                        "(T-063 MUST-FIX 2: symlink_containment_escape, end-to-end direct base)",
                    )
                    check(
                        any(
                            v["detail"].endswith("cites `pkg/ghost.py` which does not exist")
                            for v in violations
                        ),
                        "verify reports `pkg/ghost.py` as dangling instead of resolving it "
                        "through a `.gitmodules` base naming an escaping symlink "
                        "(T-063 MUST-FIX 2: symlink_containment_escape, end-to-end .gitmodules base)",
                    )
                    check(
                        any(
                            v["detail"].endswith("cites `pkg/external.md` which does not exist")
                            for v in violations
                        ),
                        "verify reports `pkg/external.md` as dangling instead of resolving it "
                        "through the suffix fallback's escaping file symlink "
                        "(T-063 MUST-FIX 2: symlink_containment_escape, end-to-end suffix fallback)",
                    )

                    # Mutation control: the escaping targets genuinely exist on disk via the
                    # symlinks -- proving the rejections above come from containment, not
                    # from the files being absent.
                    check(
                        (symlink_project / "link" / "pkg" / "ghost.py").resolve().is_file()
                        and (symlink_project / "deep" / "pkg" / "external.md").resolve().is_file(),
                        "mutation control: both escaping symlink targets genuinely resolve to "
                        "real files on disk (proves containment, not absence, drives the "
                        "rejections above)",
                    )
                else:
                    print("  (skipped: git unavailable -- symlink_containment_escape counterexample)")
            else:
                print("  (skipped: symlinks unsupported on this filesystem -- symlink_containment_escape counterexample)")
        finally:
            shutil.rmtree(symlink_root, ignore_errors=True)
    else:
        print("  (skipped: os.symlink unavailable on this platform -- symlink_containment_escape counterexample)")

    print("  T-064: suffix downgrade to hint-only + MUST-FIX B/C (final decision, user-confirmed 2026-07-26)")

    # T-064 MUST-FIX C counterexample 1/2: symlink_dotdot_normpath_order, direct base.
    # `link/../escape.md` where `link` is a project-internal symlink pointing OUTSIDE
    # the project. Pre-fix, `_resolve_in_project` normpath-folded the join BEFORE
    # containment-checking it, which lexically erases `link/..` without ever
    # consulting the symlink -- landing on the bare `escape.md`, which happens to
    # exist inside the project too (a different, coincidentally same-named file) and
    # passes containment trivially. Codex T-064 repro: pre-fix this citation resolves
    # (wrongly, and against the wrong file); post-fix it must be dangling.
    if hasattr(os, "symlink"):
        order_root = REPO_ROOT / ".tmp" / f"verify-fixture-order-{uuid.uuid4().hex}"
        order_project = order_root / "project"
        order_outside = order_root / "outside"
        round_dir9 = order_project / ".harnessloop" / "goals" / "20260110-001-fixture" / "rounds" / "0001"
        try:
            (round_dir9 / "evidence").mkdir(parents=True)
            (round_dir9 / "reviews").mkdir(parents=True)
            (round_dir9 / "scope-lock.md").write_text(
                "# Scope Lock\n\n## Allowed Changes\n\n"
                "- Write evidence under `rounds/0001/evidence/`.\n"
                "- Write reviews under `rounds/0001/reviews/`.\n",
                encoding="utf-8",
            )
            (order_outside / "sub").mkdir(parents=True)
            (order_outside / "escape.md").write_text("outside the project\n", encoding="utf-8")
            (order_project / "escape.md").write_text(
                "coincidentally same-named file actually inside the project\n", encoding="utf-8"
            )

            symlinks_supported = True
            try:
                (order_project / "link").symlink_to(order_outside / "sub", target_is_directory=True)
            except (OSError, NotImplementedError):
                symlinks_supported = False

            if symlinks_supported:
                # Mutation control: reproduce the pre-fix order verbatim (normpath the
                # join BEFORE containment-checking it) and confirm it WOULD wrongly
                # land on, and accept, the coincidentally-named in-project file --
                # proving the fix below (canonical-first) is load-bearing, not vacuous.
                old_style_candidate = Path(
                    os.path.normpath(str(order_project / "link/../escape.md"))
                )
                check(
                    old_style_candidate == (order_project / "escape.md")
                    and verify_protocol._is_contained(old_style_candidate, order_project),
                    "mutation control: normpath-before-canonicalize (the pre-T-064 order) "
                    "erases `link/..` and lands on the coincidentally-named in-project "
                    "`escape.md`, reporting it contained (proves MUST-FIX C is load-bearing)",
                )
                resolved = verify_protocol._resolve_in_project(
                    order_project, "link/../escape.md", order_project
                )
                check(
                    resolved is None,
                    "_resolve_in_project rejects `link/../escape.md`: canonical-first "
                    "resolution follows `link` to its real (outside-the-project) target "
                    "before applying `..`, instead of silently accepting a "
                    "coincidentally-named in-project file (T-064 MUST-FIX C: "
                    "symlink_dotdot_normpath_order, direct base)",
                )

                (round_dir9 / "reviews" / "order.md").write_text(
                    "Citation escaping through a symlink-then-`..` round-trip, must NOT "
                    "resolve (and must not silently land on the coincidentally-named "
                    "in-project file of the same basename):\n"
                    "- `link/../escape.md`\n",
                    encoding="utf-8",
                )
                violations, _cov = verify_protocol.verify_project(order_project)
                check(
                    any("link/../escape.md" in v["detail"] for v in violations),
                    "verify reports `link/../escape.md` as dangling instead of resolving "
                    "it against the wrong coincidentally-named project-internal file "
                    "(T-064 MUST-FIX C: symlink_dotdot_normpath_order, end-to-end direct base)",
                )
            else:
                print("  (skipped: symlinks unsupported -- symlink_dotdot_normpath_order direct-base counterexample)")
        finally:
            shutil.rmtree(order_root, ignore_errors=True)
    else:
        print("  (skipped: os.symlink unavailable -- symlink_dotdot_normpath_order direct-base counterexample)")

    # T-064 MUST-FIX C counterexample 2/2: symlink_dotdot_normpath_order, .gitmodules
    # base. `path = smod/../mod` where `smod` is a project-internal symlink pointing
    # outside the project, and the escaping target (`<outside>/mod`) genuinely exists
    # as a directory. Pre-fix, `submodule_roots` containment-checked a normpath-folded
    # copy (`project/mod`, always "inside") while accepting the directory via the RAW,
    # unfolded `candidate.is_dir()` (which follows the symlink to the real, escaping
    # target) -- the two checks disagreed about which path was in play, and the
    # escaping root was accepted.
    if hasattr(os, "symlink"):
        gm_root = REPO_ROOT / ".tmp" / f"verify-fixture-gitmodules-order-{uuid.uuid4().hex}"
        gm_project = gm_root / "project"
        gm_outside = gm_root / "outside"
        round_dir10 = gm_project / ".harnessloop" / "goals" / "20260111-001-fixture" / "rounds" / "0001"
        try:
            (round_dir10 / "evidence").mkdir(parents=True)
            (round_dir10 / "reviews").mkdir(parents=True)
            (round_dir10 / "scope-lock.md").write_text(
                "# Scope Lock\n\n## Allowed Changes\n\n"
                "- Write evidence under `rounds/0001/evidence/`.\n"
                "- Write reviews under `rounds/0001/reviews/`.\n",
                encoding="utf-8",
            )
            (gm_outside / "sub").mkdir(parents=True)
            (gm_outside / "mod" / "pkg").mkdir(parents=True)
            (gm_outside / "mod" / "pkg" / "modghost.py").write_text("# outside the project\n", encoding="utf-8")

            symlinks_supported = True
            try:
                (gm_project / "smod").symlink_to(gm_outside / "sub", target_is_directory=True)
            except (OSError, NotImplementedError):
                symlinks_supported = False

            if symlinks_supported:
                (gm_project / ".gitmodules").write_text(
                    '[submodule "escaped"]\n\tpath = smod/../mod\n\turl = https://example.invalid/escaped.git\n',
                    encoding="utf-8",
                )

                # Mutation control: reproduce the pre-fix order verbatim and confirm it
                # WOULD accept this .gitmodules path as a resolution base.
                old_style_candidate = Path(os.path.normpath(str(gm_project / "smod/../mod")))
                raw_candidate = gm_project / "smod/../mod"
                check(
                    verify_protocol._is_contained(old_style_candidate, gm_project)
                    and raw_candidate.is_dir()
                    and verify_protocol._canonical(raw_candidate) == verify_protocol._canonical(gm_outside / "mod"),
                    "mutation control: the pre-T-064 order containment-checks a "
                    "normpath-folded (always 'inside') copy while accepting the RAW "
                    "candidate's is_dir() (which follows the symlink to the real, "
                    "escaping `outside/mod`) -- the two disagree, proving MUST-FIX C is "
                    "load-bearing for the .gitmodules path too",
                )

                roots = verify_protocol.submodule_roots(gm_project)
                check(
                    all(
                        verify_protocol._canonical(r) != verify_protocol._canonical(gm_outside / "mod")
                        for r in roots
                    ),
                    "submodule_roots rejects a `.gitmodules` `path = smod/../mod` entry "
                    "whose symlink-then-`..` round-trip resolves outside the project "
                    "(T-064 MUST-FIX C: symlink_dotdot_normpath_order, .gitmodules base)",
                )

                (round_dir10 / "reviews" / "gitmodules-order.md").write_text(
                    "Citation only resolvable via a `.gitmodules` path escaping through "
                    "smod/../mod, must NOT resolve:\n"
                    "- `pkg/modghost.py`\n",
                    encoding="utf-8",
                )
                violations, _cov = verify_protocol.verify_project(gm_project)
                check(
                    any("pkg/modghost.py" in v["detail"] for v in violations),
                    "verify reports `pkg/modghost.py` as dangling instead of resolving it "
                    "through an escaping `.gitmodules` path (T-064 MUST-FIX C: "
                    "symlink_dotdot_normpath_order, end-to-end .gitmodules base)",
                )
            else:
                print("  (skipped: symlinks unsupported -- symlink_dotdot_normpath_order .gitmodules-base counterexample)")
        finally:
            shutil.rmtree(gm_root, ignore_errors=True)
    else:
        print("  (skipped: os.symlink unavailable -- symlink_dotdot_normpath_order .gitmodules-base counterexample)")

    # T-064 MUST-FIX B counterexample: stale_tracked_ghost_ambiguity. `git ls-files
    # --cached` lists a path the index still has even though it was deleted from the
    # worktree without `git rm`. Such a ghost sharing a suffix with a genuinely unique
    # real file must not suppress that file's hint by making it look ambiguous.
    ghost_root = REPO_ROOT / ".tmp" / f"verify-fixture-ghost-{uuid.uuid4().hex}"
    ghost_round = ghost_root / ".harnessloop" / "goals" / "20260112-001-fixture" / "rounds" / "0001"
    try:
        (ghost_round / "evidence").mkdir(parents=True)
        (ghost_round / "reviews").mkdir(parents=True)
        (ghost_round / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (ghost_root / "src" / "pkg").mkdir(parents=True)
        (ghost_root / "src" / "pkg" / "real.md").write_text("real\n", encoding="utf-8")
        (ghost_root / "gone" / "pkg").mkdir(parents=True)
        (ghost_root / "gone" / "pkg" / "real.md").write_text("about to be deleted\n", encoding="utf-8")

        (ghost_round / "reviews" / "ghost.md").write_text(
            "Suffix-unique citation to a real, tracked file that shares its suffix with "
            "a since-deleted (but still tracked) ghost entry -- must be dangling (no "
            "explicit base resolves it) but its hint must still fire, unsuppressed by "
            "the ghost:\n"
            "- `pkg/real.md`\n",
            encoding="utf-8",
        )

        git_available = shutil.which("git") is not None
        if git_available:
            init = subprocess.run(["git", "init", "-q"], cwd=ghost_root, capture_output=True)
            add = subprocess.run(["git", "add", "-A"], cwd=ghost_root, capture_output=True)
            git_available = init.returncode == 0 and add.returncode == 0

        if git_available:
            os.remove(ghost_root / "gone" / "pkg" / "real.md")

            # Mutation control: `git ls-files --cached` (the raw source
            # `_git_tracked_index` reads) still lists the deleted ghost entry --
            # proving any fix must be applied in our own filtering, not something git
            # already does for us.
            cached = subprocess.run(
                ["git", "-C", str(ghost_root), "ls-files", "-z", "--cached"],
                capture_output=True,
            )
            cached_entries = {seg.decode("utf-8") for seg in cached.stdout.split(b"\0") if seg}
            check(
                "gone/pkg/real.md" in cached_entries and not (ghost_root / "gone" / "pkg" / "real.md").exists(),
                "mutation control: `git ls-files --cached` still lists gone/pkg/real.md "
                "even though it no longer exists on disk (proves the ghost must be "
                "filtered by our own index-building code, not by git itself)",
            )

            ghost_index = verify_protocol.build_suffix_index(ghost_root)
            check(
                ("gone", "pkg", "real.md") not in ghost_index.get("real.md", []),
                "build_suffix_index drops a tracked-but-deleted-from-worktree ghost "
                "entry (T-064 MUST-FIX B: stale_tracked_ghost_ambiguity)",
            )
            check(
                verify_protocol.suffix_unique_match("pkg/real.md", ghost_index, ghost_root) is True,
                "suffix_unique_match sees `pkg/real.md` as unique once the ghost entry "
                "is excluded, instead of falsely ambiguous against a file that no "
                "longer exists (T-064 MUST-FIX B: stale_tracked_ghost_ambiguity)",
            )

            violations, coverage = verify_protocol.verify_project(ghost_root)
            hit = next((v for v in violations if "pkg/real.md" in v["detail"]), None)
            check(
                hit is not None and "a unique suffix match exists at src/pkg/real.md" in hit["detail"],
                f"T-064: `pkg/real.md` is dangling but carries a suffix hint unsuppressed "
                f"by the deleted ghost entry (got: {hit})",
            )
            check(
                coverage.get("citations_suffix_hinted") == 1,
                "T-064: citations_suffix_hinted counts the ghost-unsuppressed hint "
                f"(got {coverage.get('citations_suffix_hinted')})",
            )
        else:
            print("  (skipped: git unavailable -- stale_tracked_ghost_ambiguity counterexample)")
    finally:
        shutil.rmtree(ghost_root, ignore_errors=True)

    # T-064 MUST-FIX A counterexample: ignored_pseudo_unique_hint. A tracked file and a
    # genuinely-existing, GITIGNORED file share a suffix. Before T-064, this made the
    # suffix fallback wrongly resolve the citation as if the tracked file were the sole
    # candidate (a false negative that tracked wherever `--exclude-standard`'s boundary
    # was drawn -- the same shape as T-063 MUST-FIX 1, moved from "untracked" to
    # "ignored"). The downgrade closes this false negative completely: the citation
    # must be dangling BOTH before and after a `git add -f` of the ignored file, since
    # suffix matching can no longer flip a verdict at all. Only the ignored file's
    # visibility to the *hint* changes (informational only, not asserted precisely
    # here, since accuracy of a hint is explicitly out of scope for pass/fail).
    ignored_root = REPO_ROOT / ".tmp" / f"verify-fixture-ignored-{uuid.uuid4().hex}"
    ignored_round = ignored_root / ".harnessloop" / "goals" / "20260113-001-fixture" / "rounds" / "0001"
    try:
        (ignored_round / "evidence").mkdir(parents=True)
        (ignored_round / "reviews").mkdir(parents=True)
        (ignored_round / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (ignored_root / "src" / "pkg").mkdir(parents=True)
        (ignored_root / "src" / "pkg" / "real.md").write_text("tracked\n", encoding="utf-8")
        (ignored_root / "scratch" / "pkg").mkdir(parents=True)
        (ignored_root / "scratch" / "pkg" / "real.md").write_text("real, but gitignored\n", encoding="utf-8")

        (ignored_round / "reviews" / "ignored.md").write_text(
            "Ambiguous suffix -- one tracked file (src/pkg/real.md) and one genuinely "
            "real, gitignored file (scratch/pkg/real.md) share this suffix; the "
            "gitignored file is invisible to the index either way, but the citation "
            "must NOT resolve regardless (T-064 downgrade: suffix matching cannot pass "
            "a citation at all anymore):\n"
            "- `pkg/real.md`\n",
            encoding="utf-8",
        )

        git_available = shutil.which("git") is not None
        if git_available:
            init = subprocess.run(["git", "init", "-q"], cwd=ignored_root, capture_output=True)
            (ignored_root / ".gitignore").write_text("scratch/\n", encoding="utf-8")
            add = subprocess.run(
                ["git", "add", ".gitignore", "src/pkg/real.md"], cwd=ignored_root, capture_output=True
            )
            git_available = init.returncode == 0 and add.returncode == 0

        if git_available:
            check_ignore = subprocess.run(
                ["git", "-C", str(ignored_root), "check-ignore", "scratch/pkg/real.md"],
                capture_output=True,
            )
            check(
                check_ignore.returncode == 0,
                "sanity: scratch/pkg/real.md is genuinely gitignored in this fixture",
            )

            violations_before, _cov = verify_protocol.verify_project(ignored_root)
            check(
                any("pkg/real.md" in v["detail"] for v in violations_before),
                "T-064: `pkg/real.md` is dangling while scratch/pkg/real.md is still "
                "gitignored-and-invisible-to-the-index -- pre-T-064 this same state "
                "would have made the suffix fallback wrongly RESOLVE the citation "
                "(T-064 MUST-FIX A: ignored_pseudo_unique_hint, closed by the downgrade)",
            )

            add_ignored = subprocess.run(
                ["git", "add", "-f", "scratch/pkg/real.md"], cwd=ignored_root, capture_output=True
            )
            if add_ignored.returncode == 0:
                violations_after, _cov = verify_protocol.verify_project(ignored_root)
                check(
                    any("pkg/real.md" in v["detail"] for v in violations_after),
                    "T-064: `pkg/real.md` is still dangling after `git add -f` makes the "
                    "same on-disk file visible to the index too -- the verdict does not "
                    "flip either way, since suffix matching can no longer resolve "
                    "anything (zero false-negative surface, the entire point of the "
                    "downgrade)",
                )
        else:
            print("  (skipped: git unavailable -- ignored_pseudo_unique_hint counterexample)")
    finally:
        shutil.rmtree(ignored_root, ignore_errors=True)

    print("  T-066 B2a: decision.md review-declaration gate (account for review, don't grow the tree)")

    def _b2a_round(root: Path) -> Path:
        round_dir = root / ".harnessloop" / "goals" / "20260112-001-fixture" / "rounds" / "0001"
        (round_dir / "evidence").mkdir(parents=True)
        (round_dir / "reviews").mkdir(parents=True)
        (round_dir / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n"
            "- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        return round_dir

    def _b2a_violations(root: Path) -> tuple[list[dict], dict]:
        return verify_protocol.verify_project(root)

    # -- unit teeth: parse_review_fields / check_review_declaration as pure helpers --
    fields = verify_protocol.parse_review_fields(
        "# Decision\n\n- Review: rounds/0001/reviews/r.md\n- Reviewer: codex\n"
        "- Review verdict: pass\n- Review digest: " + "a" * 64 + "\n"
    )
    check(
        fields == {
            "review": "rounds/0001/reviews/r.md",
            "reviewer": "codex",
            "review_verdict": "pass",
            "review_digest": "a" * 64,
        },
        f"parse_review_fields extracts all four B2a fields verbatim (got {fields})",
    )
    check(
        verify_protocol.parse_review_fields("# Decision\n\n- Feedback: positive\n")
        == {"review": None, "reviewer": None, "review_verdict": None, "review_digest": None},
        "parse_review_fields returns None for every field absent from decision.md "
        "(distinguishes 'never written' from 'written empty')",
    )
    # Prefix-collision guard: "- Reviewer:" must not be captured by the "- Review:"
    # prefix, and "- Review verdict:"/"- Review digest:" must not be captured by
    # "- Review:" either -- this is the load-bearing property that lets all four
    # fields share the "- Review" prefix without one shadowing another.
    collision_fields = verify_protocol.parse_review_fields(
        "# Decision\n\n- Reviewer: codex\n- Review verdict: pass\n- Review digest: "
        + "b" * 64
        + "\n- Review: rounds/0001/reviews/r.md\n"
    )
    check(
        collision_fields["reviewer"] == "codex"
        and collision_fields["review_verdict"] == "pass"
        and collision_fields["review_digest"] == "b" * 64
        and collision_fields["review"] == "rounds/0001/reviews/r.md",
        f"parse_review_fields: no '- Review*' field shadows another regardless of line "
        f"order (got {collision_fields})",
    )
    # Mutation control: a naive single `startswith(\"- review:\")` check (the bug this
    # ordering guards against) WOULD wrongly capture the "- Reviewer:" line's value as
    # the "review" field -- proving the four-way branching above is load-bearing, not
    # vacuous (no real code path does this naive check; this recomputes it directly to
    # show what the bug would look like).
    naive_review_value = next(
        (
            line.strip().split(":", 1)[1].strip()
            for line in "# Decision\n\n- Reviewer: codex\n".splitlines()
            if line.strip().lower().startswith("- review:")
        ),
        None,
    )
    check(
        naive_review_value is None,
        "sanity: '- Reviewer: codex'.strip().lower() does not start with '- review:' "
        "(confirms the four fields' prefixes are genuinely disjoint, not merely handled "
        "by branch ordering)",
    )

    # -- teeth 1/5: missing required field(s) -- bidirectional --
    missing_root = REPO_ROOT / ".tmp" / f"verify-fixture-b2a-missing-{uuid.uuid4().hex}"
    try:
        round_dir = _b2a_round(missing_root)
        (round_dir / "decision.md").write_text("# Decision\n\n- Feedback: positive\n", encoding="utf-8")
        violations, coverage = _b2a_violations(missing_root)
        missing_v = [v for v in violations if v["kind"] == "review-declaration-missing"]
        check(len(missing_v) == 1, f"missing Review/Reviewer/Review verdict -> review-declaration-missing (got {[v['kind'] for v in violations]})")
        check(
            missing_v and all(label in missing_v[0]["detail"] for label in ("Review", "Reviewer", "Review verdict")),
            f"review-declaration-missing names all three absent fields (got {missing_v[0]['detail'] if missing_v else None})",
        )
        check(coverage.get("rounds_review_missing_fields") == 1, f"coverage counts rounds_review_missing_fields=1 (got {coverage})")
        check(
            not any(v["kind"] in ("rule-a", "rule-b", "dangling-citation", "scope-lock-violation") for v in missing_v),
            "review-declaration-missing does not masquerade as a Rule A/B kind",
        )

        # Reverse mutation: partially fill (Review + Reviewer, still missing verdict)
        # must still violate, but name only the one still-missing field.
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: none — no review pilot yet\n- Reviewer: codex\n", encoding="utf-8"
        )
        violations, _coverage = _b2a_violations(missing_root)
        partial_v = [v for v in violations if v["kind"] == "review-declaration-missing"]
        check(
            len(partial_v) == 1 and "Review verdict" in partial_v[0]["detail"]
            and "Reviewer" not in partial_v[0]["detail"].split("field(s): ", 1)[1].split(" (B2a")[0],
            f"partially-filled declaration still violates, naming only the field(s) still "
            f"absent (got {partial_v[0]['detail'] if partial_v else None})",
        )

        # Full reverse mutation: all three present -> no review-declaration-missing.
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: none — no review pilot yet\n- Reviewer: codex\n"
            "- Review verdict: not-applicable\n",
            encoding="utf-8",
        )
        violations, coverage = _b2a_violations(missing_root)
        check(
            not any(v["kind"] == "review-declaration-missing" for v in violations),
            "all three required fields present -> review-declaration-missing clears (reverse mutation)",
        )
        check(coverage.get("rounds_review_none") == 1, f"coverage counts rounds_review_none=1 (got {coverage})")

        # A round with no decision.md at all must never trip this rule (zero-migration
        # for rounds that have not reached the decision step yet, same discipline E4 uses).
        (round_dir / "decision.md").unlink()
        violations, coverage = _b2a_violations(missing_root)
        check(
            not any(v["kind"].startswith("review-") for v in violations),
            "a round with no decision.md at all triggers no review-declaration violation",
        )
        check(
            coverage.get("rounds_review_missing_fields") == 0
            and coverage.get("rounds_review_none") == 0
            and coverage.get("rounds_review_declared") == 0,
            f"coverage stays zero for a round with no decision.md (got {coverage})",
        )
    finally:
        shutil.rmtree(missing_root, ignore_errors=True)

    # -- teeth 2/5: Review: none — <reason> -- empty vs non-empty, bidirectional --
    none_root = REPO_ROOT / ".tmp" / f"verify-fixture-b2a-none-{uuid.uuid4().hex}"
    try:
        round_dir = _b2a_round(none_root)
        for empty_reason in ("none", "none —", "none -", "none —   ", "none-"):
            (round_dir / "decision.md").write_text(
                f"# Decision\n\n- Review: {empty_reason}\n- Reviewer: codex\n- Review verdict: not-applicable\n",
                encoding="utf-8",
            )
            violations, _coverage = _b2a_violations(none_root)
            check(
                any(v["kind"] == "review-none-reason-empty" for v in violations),
                f"`Review: {empty_reason!r}` (empty/whitespace-only reason) -> "
                f"review-none-reason-empty (got {[v['kind'] for v in violations]})",
            )
        # Reverse mutation: same shape, non-empty reason -> passes.
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: none — B1 not yet closed for this round's language\n"
            "- Reviewer: codex\n- Review verdict: not-applicable\n",
            encoding="utf-8",
        )
        violations, coverage = _b2a_violations(none_root)
        check(
            not any(v["kind"] == "review-none-reason-empty" for v in violations),
            "`Review: none — <non-empty reason>` clears review-none-reason-empty (reverse mutation)",
        )
        check(coverage.get("rounds_review_none") == 1, f"coverage counts rounds_review_none=1 (got {coverage})")
        # Mechanical-only guard (explicit non-goal): this rule must not reject a
        # transparently-weak reason -- it can only check non-emptiness, never adequacy.
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: none — x\n- Reviewer: codex\n- Review verdict: not-applicable\n",
            encoding="utf-8",
        )
        violations, _coverage = _b2a_violations(none_root)
        check(
            not any(v["kind"].startswith("review-") for v in violations),
            "a minimal but non-empty reason ('x') passes -- this rule mechanically checks "
            "non-emptiness only, never reason adequacy (see check_review_declaration docstring)",
        )
    finally:
        shutil.rmtree(none_root, ignore_errors=True)

    # -- teeth 3/5: Review: <path> -- not-found / escapes-project / symlink / directory
    # / plain-file, bidirectional --
    path_root = REPO_ROOT / ".tmp" / f"verify-fixture-b2a-path-{uuid.uuid4().hex}"
    try:
        round_dir = _b2a_round(path_root)
        review_file = round_dir / "reviews" / "r1.md"
        review_file.write_text("adversarial review body\n", encoding="utf-8")
        review_rel = review_file.relative_to(path_root).as_posix()

        # not-found
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: "
            + round_dir.relative_to(path_root).as_posix()
            + "/reviews/does-not-exist.md\n- Reviewer: codex\n- Review verdict: pass\n",
            encoding="utf-8",
        )
        violations, _coverage = _b2a_violations(path_root)
        check(
            any(v["kind"] == "review-path-not-found" for v in violations),
            f"nonexistent Review path -> review-path-not-found (got {[v['kind'] for v in violations]})",
        )

        # escapes project (literal ../ walk)
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: ../../../../../../../../etc/hosts\n- Reviewer: codex\n- Review verdict: pass\n",
            encoding="utf-8",
        )
        violations, _coverage = _b2a_violations(path_root)
        check(
            any(v["kind"] == "review-path-escapes-project" for v in violations),
            f"Review path escaping the project via literal '../' -> review-path-escapes-project "
            f"(got {[v['kind'] for v in violations]})",
        )

        # is a directory, not a file
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: "
            + round_dir.relative_to(path_root).as_posix()
            + "/reviews\n- Reviewer: codex\n- Review verdict: pass\n",
            encoding="utf-8",
        )
        violations, _coverage = _b2a_violations(path_root)
        check(
            any(v["kind"] == "review-path-not-file" for v in violations),
            f"Review path naming a directory -> review-path-not-file (got {[v['kind'] for v in violations]})",
        )

        # symlink (even one whose target legitimately resolves inside the project)
        if hasattr(os, "symlink"):
            link = round_dir / "reviews" / "link.md"
            symlinks_supported = True
            try:
                link.symlink_to(review_file)
            except (OSError, NotImplementedError):
                symlinks_supported = False
            if symlinks_supported:
                (round_dir / "decision.md").write_text(
                    "# Decision\n\n- Review: "
                    + link.relative_to(path_root).as_posix()
                    + "\n- Reviewer: codex\n- Review verdict: pass\n",
                    encoding="utf-8",
                )
                violations, _coverage = _b2a_violations(path_root)
                check(
                    any(v["kind"] == "review-path-is-symlink" for v in violations),
                    f"Review path naming a symlink (target legitimately inside the project) -> "
                    f"review-path-is-symlink (got {[v['kind'] for v in violations]})",
                )
                # Mutation control: the symlink's target genuinely exists and is a plain
                # file -- proving the rejection above is the leaf-is-symlink check firing,
                # not existence or containment (which both pass for this target).
                check(
                    verify_protocol._is_contained(link, path_root) and review_file.is_file(),
                    "mutation control: the symlink's own path is project-contained and its "
                    "target is a real plain file -- proves review-path-is-symlink fires "
                    "specifically because the leaf is a symlink, not because of containment "
                    "or existence",
                )
                link.unlink()
            else:
                print("  (skipped: symlinks unsupported -- review-path-is-symlink case)")
        else:
            print("  (skipped: os.symlink unavailable -- review-path-is-symlink case)")

        # T-063/T-064-style symlink escape: a project-internal symlink whose target is
        # OUTSIDE the project must fail containment, not merely "is a symlink" -- reusing
        # the same _is_contained discipline Rule B's citation resolution relies on.
        if hasattr(os, "symlink"):
            outside_dir = path_root.parent / f"b2a-outside-{uuid.uuid4().hex}"
            (outside_dir).mkdir(parents=True)
            (outside_dir / "external-review.md").write_text("outside the project\n", encoding="utf-8")
            escape_link = round_dir / "reviews" / "escape-link.md"
            symlinks_supported = True
            try:
                escape_link.symlink_to(outside_dir / "external-review.md")
            except (OSError, NotImplementedError):
                symlinks_supported = False
            if symlinks_supported:
                (round_dir / "decision.md").write_text(
                    "# Decision\n\n- Review: "
                    + escape_link.relative_to(path_root).as_posix()
                    + "\n- Reviewer: codex\n- Review verdict: pass\n",
                    encoding="utf-8",
                )
                violations, _coverage = _b2a_violations(path_root)
                kinds = {v["kind"] for v in violations}
                check(
                    "review-path-escapes-project" in kinds,
                    f"Review path naming a project-internal symlink whose TARGET is outside "
                    f"the project -> review-path-escapes-project, same discipline as Rule B's "
                    f"symlink_containment_escape (got {kinds})",
                )
                # Mutation control: lexical normpath containment alone WOULD accept this --
                # the symlink's own path is inside the project even though its target is not.
                check(
                    verify_protocol.is_under(escape_link, path_root)
                    and not verify_protocol._is_contained(escape_link, path_root),
                    "mutation control: lexical containment passes this symlink while canonical "
                    "(_is_contained) containment correctly rejects it -- proves the escape is "
                    "caught by symlink resolution, not merely by chance",
                )
                escape_link.unlink()
            else:
                print("  (skipped: symlinks unsupported -- Review symlink-escape counterexample)")
            shutil.rmtree(outside_dir, ignore_errors=True)

        # Reverse mutation: an ordinary, project-contained, non-symlink, existing file ->
        # no review-path-* violation at all, and coverage counts it as declared.
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: " + review_rel + "\n- Reviewer: codex\n- Review verdict: pass\n",
            encoding="utf-8",
        )
        violations, coverage = _b2a_violations(path_root)
        check(
            not any(v["kind"].startswith("review-path") for v in violations),
            f"an ordinary project-contained non-symlink existing file -> no review-path-* "
            f"violation (reverse mutation; got {[v['kind'] for v in violations]})",
        )
        check(coverage.get("rounds_review_declared") == 1, f"coverage counts rounds_review_declared=1 (got {coverage})")
    finally:
        shutil.rmtree(path_root, ignore_errors=True)

    # -- teeth 4/5: Review digest -- mismatch / match / undeclared, bidirectional --
    digest_root = REPO_ROOT / ".tmp" / f"verify-fixture-b2a-digest-{uuid.uuid4().hex}"
    try:
        round_dir = _b2a_round(digest_root)
        review_file = round_dir / "reviews" / "r1.md"
        review_file.write_text("adversarial review body for digest test\n", encoding="utf-8")
        review_rel = review_file.relative_to(digest_root).as_posix()
        real_digest = hashlib.sha256(review_file.read_bytes()).hexdigest()

        # mismatch
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: " + review_rel + "\n- Reviewer: codex\n- Review verdict: pass\n"
            "- Review digest: " + ("f" * 64) + "\n",
            encoding="utf-8",
        )
        violations, coverage = _b2a_violations(digest_root)
        check(
            any(v["kind"] == "review-digest-mismatch" for v in violations),
            f"wrong Review digest -> review-digest-mismatch (got {[v['kind'] for v in violations]})",
        )
        check(coverage.get("rounds_review_digest_declared") == 1, f"coverage counts a declared (even mismatching) digest (got {coverage})")

        # reverse mutation: correct digest -> clears
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: " + review_rel + "\n- Reviewer: codex\n- Review verdict: pass\n"
            "- Review digest: " + real_digest + "\n",
            encoding="utf-8",
        )
        violations, coverage = _b2a_violations(digest_root)
        check(
            not any(v["kind"] == "review-digest-mismatch" for v in violations),
            "correct Review digest clears review-digest-mismatch (reverse mutation)",
        )
        check(coverage.get("rounds_review_digest_declared") == 1, f"coverage counts the matching declared digest too (got {coverage})")

        # undeclared digest is never a violation and never counted
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: " + review_rel + "\n- Reviewer: codex\n- Review verdict: pass\n",
            encoding="utf-8",
        )
        violations, coverage = _b2a_violations(digest_root)
        check(
            not any(v["kind"] == "review-digest-mismatch" for v in violations),
            "Review digest is optional -- omitting it entirely is never a violation",
        )
        check(coverage.get("rounds_review_digest_declared") == 0, f"coverage counts 0 when no digest is declared (got {coverage})")

        # Mutation control: the review file genuinely changed content since the digest
        # would have been computed for the original body -- proving the mismatch above
        # is a real content check, not a string-format check.
        check(
            hashlib.sha256(review_file.read_bytes()).hexdigest() == real_digest,
            "mutation control: the review file's live sha256 still matches real_digest at "
            "this point (proves the earlier mismatch used a wrong-but-well-formed digest, "
            "not a file that had actually changed)",
        )
    finally:
        shutil.rmtree(digest_root, ignore_errors=True)

    # -- teeth 5/5: B2a explicitly does NOT fold a declared review file into Rule A/B --
    # this is the actual meaning of "account for it, don't grow the tree": B2a places no
    # requirement that Review: point *into* reviews/ (that would be B2b), and a review
    # dense with dangling-looking citations, declared from OUTSIDE round_dir/reviews/ (so
    # Rule B's own, pre-existing, unconditional reviews/*.md walk cannot independently
    # trip over it either), must still produce zero dangling-citation violations and
    # leave rule_b_files/citations_checked untouched -- proving B2a's own logic never
    # reads the file's prose or invokes Rule B's citation extraction on it.
    notree_root = REPO_ROOT / ".tmp" / f"verify-fixture-b2a-notree-{uuid.uuid4().hex}"
    try:
        round_dir = _b2a_round(notree_root)
        review_file = notree_root / "external-reviews" / "dense.md"
        review_file.parent.mkdir(parents=True)
        review_file.write_text(
            "This review cites many things that do not exist:\n"
            "- `totally/made/up/path/one.md`\n"
            "- `another/totally/made/up/path.py`\n"
            "- `yet/another/nonexistent/reference.md`\n",
            encoding="utf-8",
        )
        (round_dir / "decision.md").write_text(
            "# Decision\n\n- Review: "
            + review_file.relative_to(notree_root).as_posix()
            + "\n- Reviewer: codex\n- Review verdict: pass\n",
            encoding="utf-8",
        )
        violations, coverage = _b2a_violations(notree_root)
        check(
            not any(v["kind"] == "dangling-citation" for v in violations),
            f"a declared Review file's own dangling-looking citations never produce "
            f"dangling-citation violations -- B2a accounts for the file, it does not scan "
            f"it (got {[v['kind'] for v in violations]})",
        )
        check(
            coverage.get("rule_b_files") == 0 and coverage.get("citations_checked") == 0,
            f"a Review file declared outside round_dir/reviews/ is invisible to both Rule "
            f"B's own independent reviews/*.md walk AND B2a's own logic -- rule_b_files "
            f"and citations_checked both stay 0 (got {coverage})",
        )
        check(
            coverage.get("rounds_review_declared") == 1,
            f"the round is still counted once in rounds_review_declared even though the "
            f"declared file lives outside reviews/ -- B2a does not require Review: to "
            f"point into reviews/ (that requirement, if any, belongs to the not-yet-built "
            f"B2b) (got {coverage})",
        )

        # Reverse half of the same point: the identical dense-citation file, this time
        # actually placed under round_dir/reviews/, IS picked up by Rule B's own
        # pre-existing, unconditional walk (unrelated to B2a) and DOES produce
        # dangling-citation violations -- proving the zero-violations result above comes
        # from B2a genuinely not scanning the file, not from the citations being
        # unreachable in principle.
        in_tree_review = round_dir / "reviews" / "dense.md"
        in_tree_review.write_text(review_file.read_text(encoding="utf-8"), encoding="utf-8")
        violations, coverage = _b2a_violations(notree_root)
        check(
            any(v["kind"] == "dangling-citation" for v in violations),
            "mutation control: the same dense-citation content, once placed under "
            "round_dir/reviews/, IS caught by Rule B's own independent walk -- proving "
            "Rule B's citation checker genuinely can (and does) fire on this content; "
            "B2a's silence on the out-of-tree copy above is not because the citations "
            "are unreachable in principle",
        )
        in_tree_review.unlink()
    finally:
        shutil.rmtree(notree_root, ignore_errors=True)


def validate_round_cost_smoke() -> None:
    print("[7/8] Round cost settlement smoke test (round_cost.py)")
    cost_script = LOOP_SCRIPTS / "round_cost.py"
    smoke_root = REPO_ROOT / ".tmp" / f"cost-smoke-{uuid.uuid4().hex}"
    project = smoke_root / "project"
    transcripts = smoke_root / "transcripts"
    try:
        project.mkdir(parents=True)
        transcripts.mkdir(parents=True)
        turn = {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": 100,
                    "cache_creation_input_tokens": 50,
                    "cache_read_input_tokens": 1000,
                    "output_tokens": 200,
                },
                "content": [{"type": "text", "text": "updating .harnessloop/state/current.md"}],
            },
        }
        business_turn = json.loads(json.dumps(turn))
        business_turn["message"]["content"] = [{"type": "text", "text": "business work"}]

        # Same-id multi-line usage: Claude Code writes one JSONL line per
        # content block of a single assistant message, and every line for
        # that message.id repeats the message's usage. round_cost.py must
        # dedupe by message.id instead of summing every line, or these two
        # lines for msg_dup001 (still "open" - no closing message after them
        # yet, mirroring round_cost.py normally being invoked from inside
        # the very message it is reporting on) would be billed twice each
        # settlement they're re-scanned in. These assertions fail against
        # the pre-fix per-line-summing logic.
        dup_block_1 = {
            "type": "assistant",
            "message": {
                "id": "msg_dup001",
                "usage": {
                    "input_tokens": 300,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 400,
                    "output_tokens": 50,
                },
                "content": [{"type": "thinking", "thinking": "planning the change"}],
            },
        }
        dup_block_2 = json.loads(json.dumps(dup_block_1))
        dup_block_2["message"]["usage"]["output_tokens"] = 120
        dup_block_2["message"]["content"] = [{"type": "tool_use", "name": "Bash", "input": {}}]

        (transcripts / "session.jsonl").write_text(
            json.dumps(turn) + "\n"
            + "garbage-line\n"
            + json.dumps(business_turn) + "\n"
            + json.dumps(dup_block_1) + "\n"
            + json.dumps(dup_block_2) + "\n",
            encoding="utf-8",
        )

        result = run_python(cost_script, "--project", str(project), "--transcript-dir", str(transcripts))
        check(result.returncode == 0, "round_cost.py exits 0 on synthetic transcript")
        check("## Cost" in result.stdout, "round_cost.py emits a ## Cost section")
        check("2 assistant turn(s)" in result.stdout, "round_cost.py counts assistant turns")
        check("1/2 turns" in result.stdout, "round_cost.py attributes protocol turns heuristically")
        check(
            "Output tokens: 400" in result.stdout,
            "round_cost.py defers the still-open msg_dup001 message instead of billing its partial lines",
        )

        marker_path = project / ".harnessloop" / "local" / "cost-marker.json"
        check(marker_path.exists(), "round_cost.py writes the settlement marker")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        pending = marker.get("files", {}).get("session.jsonl", {})
        check(
            pending.get("offset") == 5
            and pending.get("pending_id") == "msg_dup001"
            and pending.get("pending_usage") == {"input": 300, "cache_write": 20, "cache_read": 400, "output": 120},
            "marker carries the still-open message.id and its max-merged usage across the settlement window",
        )

        # Continue the session: msg_dup001's 3rd (final) content-block line
        # arrives, then a genuinely new message (msg_next002) closes it out.
        # This is the cross-settlement-window case: msg_dup001's lines are
        # split across two round_cost.py runs by the marker offset above,
        # and must still be billed exactly once (using its max usage, not
        # the sum of all 3 lines: 50 + 120 + 150 = 320 would be wrong).
        dup_block_3 = json.loads(json.dumps(dup_block_1))
        dup_block_3["message"]["usage"]["output_tokens"] = 150
        dup_block_3["message"]["content"] = [
            {"type": "text", "text": "done, see .harnessloop/round-summary.md"}
        ]
        next_turn = {
            "type": "assistant",
            "message": {
                "id": "msg_next002",
                "usage": {
                    "input_tokens": 77,
                    "cache_creation_input_tokens": 5,
                    "cache_read_input_tokens": 10,
                    "output_tokens": 33,
                },
                "content": [{"type": "text", "text": "next turn, business as usual"}],
            },
        }
        with (transcripts / "session.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dup_block_3) + "\n")
            fh.write(json.dumps(next_turn) + "\n")

        result = run_python(cost_script, "--project", str(project), "--transcript-dir", str(transcripts))
        check(result.returncode == 0, "round_cost.py exits 0 on the continuation window")
        check(
            "1 assistant turn(s)" in result.stdout,
            "round_cost.py bills msg_dup001 exactly once, on the run that observes its closing message",
        )
        check(
            "Input tokens: 300" in result.stdout and "Output tokens: 150" in result.stdout,
            "deduped total matches msg_dup001's max usage across its 3 lines, not their sum (50+120+150=320)",
        )
        check(
            "1/1 turns" in result.stdout and "100% of output" in result.stdout,
            "protocol attribution (mentioned only in msg_dup001's 3rd line) still applies to the whole deduped message",
        )

        result = run_python(cost_script, "--project", str(project), "--transcript-dir", str(transcripts))
        check(
            result.returncode == 0 and "0 assistant turn(s)" in result.stdout,
            "third settlement reports an empty incremental window (msg_next002 still open, deferred)",
        )

        result = run_python(cost_script, "--project", str(project), "--transcript-dir", str(smoke_root / "missing"))
        check(result.returncode == 2, "missing transcript dir exits 2")
    finally:
        shutil.rmtree(smoke_root, ignore_errors=True)


def validate_claude_strict() -> None:
    print("[8/8] Claude strict plugin validation")
    if os.environ.get("HARNESSLOOP_SKIP_CLAUDE") == "1":
        print("  skipped: HARNESSLOOP_SKIP_CLAUDE=1")
        return

    claude = (
        shutil.which("claude")
        or shutil.which("claude.cmd")
        or shutil.which("claude.exe")
        or os.environ.get("CLAUDE_CLI")
    )
    if not claude:
        check(False, "claude CLI found on PATH (or set CLAUDE_CLI, or HARNESSLOOP_SKIP_CLAUDE=1)")
        return

    for target in (REPO_ROOT, PLUGIN_ROOT):
        result = subprocess.run(
            [claude, "plugin", "validate", "--strict", str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        passed = result.returncode == 0 and "Validation failed" not in output
        check(passed, f"claude plugin validate --strict {target.name or target}")
        if not passed:
            print(output)


def main() -> int:
    validate_manifests()
    validate_init_smoke()
    validate_check_setup_smoke()
    validate_secrets_smoke()
    validate_doc_consistency()
    validate_protocol_gates()
    validate_round_cost_smoke()
    validate_claude_strict()

    print()
    if FAILURES:
        print(f"Validation FAILED: {len(FAILURES)} check(s) did not pass.")
        return 1
    print("Plugin framework validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
