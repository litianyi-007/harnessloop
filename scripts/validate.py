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


def validate_protocol_gates() -> None:
    print("[6/8] Mechanical protocol gates (verify_protocol.py)")
    mock_project = REPO_ROOT / "examples" / "mock-project"
    violations, _coverage = verify_protocol.verify_project(mock_project)
    check(not violations, f"examples/mock-project passes verify ({len(violations)} violation(s))")
    for violation in violations:
        print(f"    {violation['kind']}: {violation['detail']}")

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
    skill_md = (
        REPO_ROOT / "plugins" / "harnessloop" / "skills" / "harnessloop-loop" / "SKILL.md"
    )
    if skill_md.exists():
        skill_text = skill_md.read_text(encoding="utf-8")
        boundary_start = skill_text.find("### Mechanical Gate Boundary")
        check(
            boundary_start != -1,
            "harnessloop-loop/SKILL.md declares the Mechanical Gate Boundary section (E1)",
        )
        if boundary_start != -1:
            boundary = skill_text[boundary_start : boundary_start + 4000]
            _, sample_coverage = verify_protocol.verify_project(REPO_ROOT.parent)
            missing = [f for f in sample_coverage if f"`{f}`" not in boundary]
            check(
                not missing,
                "every coverage field is named in the SKILL.md IN column "
                f"(missing: {missing})",
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
