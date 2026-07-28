#!/usr/bin/env python3
"""Cross-platform Harnessloop repository validation.

Checks, in order:
1. Manifest and marketplace invariants (Codex + Claude).
2. Version consistency across every manifest carrying a semantic version
   (G28): discovered by a filesystem walk keyed on basename
   (package.json / plugin.json / marketplace.json), not a hardcoded list,
   with teeth proving the discovery mechanism itself (mutation -> red,
   brand-new manifest path -> picked up automatically, integer schema
   `"version": 1` fields -> correctly ignored).
3. Init smoke test (skeleton creation, intake packet).
4. Setup completeness smoke test (check_setup.py) on a skeleton project and a
   programmatically-filled fixture, including the double-gate (gate_blocking
   vs complete) regression cases.
5. Secrets smoke test (channel-params store, gitignore protection, no values).
6. Documentation skeleton consistency against init_project.py (single source of truth).
7. Mechanical protocol gates (verify_protocol.py) on examples/mock-project,
   including negative fixtures that must fail.
8. Round cost settlement smoke test (round_cost.py) on a synthetic transcript.
9. Claude strict plugin validation (skippable via HARNESSLOOP_SKIP_CLAUDE=1
   for environments without the claude CLI, e.g. bare CI runners).

Exit code 0 = all passed.
"""

from __future__ import annotations

import hashlib
import inspect
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

# ---------------------------------------------------------------------------
# windows-latest defaults its stdout/stderr encoding to the legacy console
# code page (cp1252 under Python 3.14), not UTF-8. This file's check()
# messages are allowed to (and do) contain non-ASCII text -- Chinese prose
# and symbols like "⇒" quoting repo-internal strings verbatim (see e.g. the
# RAE gate messages below) -- and printing one of those under cp1252 raises
# UnicodeEncodeError, which aborts the whole run before any later check
# executes (observed: v0.27.0+ CI, windows-latest, Python 3.14). Force UTF-8
# explicitly rather than stripping non-ASCII text from messages: the next
# message added anywhere in this file could just as easily reintroduce the
# same crash. errors="backslashreplace" (not "replace") so a genuinely
# unencodable character still leaves a visible escaped sequence in the CI
# log instead of silently vanishing. See G29a below for the teeth.
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")

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


# ---------------------------------------------------------------------------
# G28: version-consistency discovery. This is a DISCOVERY mechanism (a
# filesystem walk keyed on basename) and must stay one -- a hardcoded list of
# "known" manifest paths would have exactly the same blind spot as the bug it
# exists to catch (plugins/harnessloop/.codex-plugin/plugin.json drifted to
# 0.11.0 for 18 minor releases with nobody noticing). Any new manifest added
# anywhere under the repo is picked up automatically; see G28c below.
# ---------------------------------------------------------------------------

VERSION_MANIFEST_FILENAMES = frozenset({"package.json", "plugin.json", "marketplace.json"})
VERSION_SCAN_EXCLUDE_DIR_NAMES = frozenset({".git", "node_modules", ".tmp", "__pycache__"})
SEMVER_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _iter_version_manifest_paths(root: Path):
    """Walk `root` and yield every package.json / plugin.json / marketplace.json,
    however deeply nested, whatever its parent directory is named. Keyed only
    on basename -- not a fixed list of paths."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in VERSION_SCAN_EXCLUDE_DIR_NAMES]
        for filename in filenames:
            if filename in VERSION_MANIFEST_FILENAMES:
                yield Path(dirpath) / filename


def _collect_semver_values(node: object, out: list[str]) -> None:
    """Recursively walk a parsed JSON value, collecting every STRING value
    keyed "version" that looks like a semantic version (`\\d+.\\d+.\\d+`).
    Integer schema-version fields such as `"version": 1` (real examples exist
    in this repo, e.g. reference-roots-template.json) are excluded by
    construction: the value must be a `str` AND match SEMVER_VERSION_RE."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "version" and isinstance(value, str) and SEMVER_VERSION_RE.match(value):
                out.append(value)
            _collect_semver_values(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_semver_values(item, out)


def discover_manifest_versions(root: Path) -> dict[Path, list[str]]:
    """Discover {manifest_path: [semver strings found in it]} for every
    package.json / plugin.json / marketplace.json under `root`. A manifest
    that yields zero qualifying semver strings (e.g. .agents/plugins/marketplace.json,
    which currently carries no "version" key at all, or a pure integer
    schema-version file) is simply omitted -- it has nothing to be
    inconsistent with."""
    discovered: dict[Path, list[str]] = {}
    for path in _iter_version_manifest_paths(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        found: list[str] = []
        _collect_semver_values(data, found)
        if found:
            discovered[path] = found
    return discovered


def _g28_write_fixture_manifest(root: Path, rel: str, data: dict) -> None:
    path = root / Path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def validate_manifests() -> None:
    print("[1/9] Manifests and marketplace entries")
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


def validate_version_consistency() -> None:
    print("[2/9] Version consistency across manifests (G28)")

    # G28a: real repo state. discover_manifest_versions() is a filesystem
    # walk keyed on basename (package.json / plugin.json / marketplace.json),
    # not a hardcoded list -- see G28c for the fixture that proves this.
    discovered = discover_manifest_versions(REPO_ROOT)
    rel_report = ", ".join(
        f"{path.relative_to(REPO_ROOT)}={versions}" for path, versions in sorted(discovered.items())
    )
    check(
        len(discovered) >= 3,
        f"G28a: version scan discovered at least 3 manifests carrying a semantic "
        f"version (found {len(discovered)}: {rel_report}) -- guards against the walk "
        "silently matching nothing",
    )
    all_versions = sorted({v for versions in discovered.values() for v in versions})
    check(
        len(all_versions) <= 1,
        f"G28a: every discovered manifest version string is identical across the repo "
        f"(discovered: {rel_report})",
    )

    # ---- G28b/c/d: teeth. Every one of these runs against a disposable
    # synthetic fixture tree built fresh in the system temp dir -- never the
    # real repo files -- using the SAME discover_manifest_versions() pointed
    # at a different root. ----

    print(
        "  G28b: mutating one manifest's version in a temp fixture must turn the "
        "guard red and name that file"
    )
    fixture_root = Path(tempfile.mkdtemp(prefix="harnessloop-g28b-"))
    try:
        _g28_write_fixture_manifest(fixture_root, "package.json", {"name": "x", "version": "1.2.3"})
        _g28_write_fixture_manifest(
            fixture_root, ".claude-plugin/marketplace.json", {"plugins": [{"name": "x", "version": "1.2.3"}]}
        )
        _g28_write_fixture_manifest(
            fixture_root, "plugins/harnessloop/.claude-plugin/plugin.json", {"name": "harnessloop", "version": "1.2.3"}
        )
        _g28_write_fixture_manifest(
            fixture_root, "plugins/harnessloop/.codex-plugin/plugin.json", {"name": "harnessloop", "version": "1.2.3"}
        )

        baseline = discover_manifest_versions(fixture_root)
        baseline_versions = sorted({v for versions in baseline.values() for v in versions})
        check(
            baseline_versions == ["1.2.3"],
            f"G28b baseline: freshly-built 4-manifest fixture (all 1.2.3) is internally "
            f"consistent before mutation (found {baseline_versions})",
        )

        mutated_path = fixture_root / "plugins" / "harnessloop" / ".codex-plugin" / "plugin.json"
        _g28_write_fixture_manifest(
            fixture_root, "plugins/harnessloop/.codex-plugin/plugin.json", {"name": "harnessloop", "version": "9.9.9"}
        )
        mutated = discover_manifest_versions(fixture_root)
        mutated_versions = sorted({v for versions in mutated.values() for v in versions})
        offenders = sorted(str(p.relative_to(fixture_root)) for p, vs in mutated.items() if "9.9.9" in vs)
        check(
            len(mutated_versions) > 1 and mutated_path in mutated and "9.9.9" in mutated[mutated_path],
            f"G28b: bumping ONLY the fixture's .codex-plugin/plugin.json to 9.9.9 (three "
            f"other manifests untouched at 1.2.3) makes the guard red AND the offending "
            f"file is nameable from the discovery result (versions found: {mutated_versions}, "
            f"offenders: {offenders})",
        )
    finally:
        shutil.rmtree(fixture_root, ignore_errors=True)

    print(
        "  G28c: a brand-new, previously-unseen manifest path must be picked up "
        "automatically (discover, not enumerate)"
    )
    fixture_root = Path(tempfile.mkdtemp(prefix="harnessloop-g28c-"))
    try:
        _g28_write_fixture_manifest(fixture_root, "package.json", {"name": "x", "version": "1.2.3"})
        _g28_write_fixture_manifest(
            fixture_root, ".claude-plugin/marketplace.json", {"plugins": [{"name": "x", "version": "1.2.3"}]}
        )
        _g28_write_fixture_manifest(
            fixture_root, "plugins/harnessloop/.claude-plugin/plugin.json", {"name": "harnessloop", "version": "1.2.3"}
        )
        _g28_write_fixture_manifest(
            fixture_root, "plugins/harnessloop/.codex-plugin/plugin.json", {"name": "harnessloop", "version": "1.2.3"}
        )

        baseline = discover_manifest_versions(fixture_root)
        check(
            sorted({v for vs in baseline.values() for v in vs}) == ["1.2.3"],
            "G28c baseline: 4-manifest fixture is consistent before the new manifest is added",
        )

        new_manifest_rel = "plugins/harnessloop/.someother-plugin/plugin.json"
        check(
            not (fixture_root / new_manifest_rel).exists(),
            f"G28c: {new_manifest_rel} genuinely does not exist yet in the fixture -- "
            "this is the 'previously non-existent manifest' case, not a pre-seeded one",
        )
        _g28_write_fixture_manifest(
            fixture_root, new_manifest_rel, {"name": "harnessloop-someother", "version": "4.5.6"}
        )

        after = discover_manifest_versions(fixture_root)
        new_path = fixture_root / Path(new_manifest_rel)
        after_versions = sorted({v for vs in after.values() for v in vs})
        check(
            new_path in after and after[new_path] == ["4.5.6"],
            f"G28c: the newly-created {new_manifest_rel} (never hardcoded anywhere in the "
            "scan logic) is present in the discovery result -- proves the walk is a real "
            "filesystem discovery keyed on basename, not a fixed enumeration of known paths",
        )
        check(
            len(after_versions) > 1,
            f"G28c: adding that one previously-unknown manifest at version 4.5.6 (three "
            f"pre-existing manifests still at 1.2.3) turns the consistency guard red "
            f"(discovered versions: {after_versions}) -- if this were green instead, the "
            "implementation would be an enumeration with a blind spot, not a discovery",
        )
    finally:
        shutil.rmtree(fixture_root, ignore_errors=True)

    print(
        "  G28d: an integer schema `\"version\": 1` field must not be misread as a "
        "plugin version"
    )
    fixture_root = Path(tempfile.mkdtemp(prefix="harnessloop-g28d-"))
    try:
        _g28_write_fixture_manifest(fixture_root, "package.json", {"name": "x", "version": "1.2.3"})
        _g28_write_fixture_manifest(
            fixture_root, ".claude-plugin/marketplace.json", {"plugins": [{"name": "x", "version": "1.2.3"}]}
        )
        _g28_write_fixture_manifest(
            fixture_root, "plugins/harnessloop/.claude-plugin/plugin.json", {"name": "harnessloop", "version": "1.2.3"}
        )
        _g28_write_fixture_manifest(
            fixture_root, "plugins/harnessloop/.codex-plugin/plugin.json", {"name": "harnessloop", "version": "1.2.3"}
        )
        # A pure integer schema-version manifest, mirroring the real, already-in-repo
        # shape of e.g. reference-roots-template.json -- except here it is placed
        # under a scanned filename (plugin.json) so it is genuinely visited by the
        # file-level walk, and must still be excluded at the value-level filter.
        schema_rel = "plugins/harnessloop/skills/some-skill/schema/plugin.json"
        _g28_write_fixture_manifest(fixture_root, schema_rel, {"version": 1})

        all_manifest_paths = set(_iter_version_manifest_paths(fixture_root))
        schema_path = fixture_root / Path(schema_rel)
        check(
            schema_path in all_manifest_paths,
            "G28d: the integer-schema plugin.json IS visited by the filename-based file "
            "walk (it is a real plugin.json on disk) -- the exclusion below happens at "
            "the value level, not by skipping the file",
        )

        result = discover_manifest_versions(fixture_root)
        check(
            schema_path not in result,
            "G28d: ...but it contributes zero entries to the version-bearing result, "
            "because its only \"version\" value is the int 1, which fails the "
            "isinstance(str) + semver-regex test",
        )
        all_versions = sorted({v for vs in result.values() for v in vs})
        check(
            all_versions == ["1.2.3"],
            f"G28d: the nested integer schema version does not get pulled into the "
            f"semantic version set alongside the real 1.2.3 manifests (discovered "
            f"versions: {all_versions}) -- the guard stays green",
        )
    finally:
        shutil.rmtree(fixture_root, ignore_errors=True)


def validate_init_smoke() -> None:
    print("[3/9] Init smoke test")
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
    print("[4/9] Setup completeness smoke test (check_setup.py)")

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
    print("[5/9] Secrets smoke test")
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
    print("[6/9] Documentation skeleton consistency (source of truth: init_project.py)")
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


# ---------------------------------------------------------------------------
# PR-3 fixture helpers (external-citation-base-spec-20260727.md §2-3). Every
# fixture root these build is a fresh `tempfile.mkdtemp()` directory -- never
# `~`, never a hardcoded real host directory (the one deliberate exception is
# G4's own use of the live `Path.home()` value, which the forbidden-root rule
# itself is defined against and must be tested with).
# ---------------------------------------------------------------------------


def _pr3_project(tmp_root: Path) -> Path:
    """A minimal project fixture: one round with `evidence/`/`reviews/`
    ready and a parseable `scope-lock.md`."""
    project = tmp_root / "project"
    round_dir = project / ".harnessloop" / "goals" / "20260101-001-pr3" / "rounds" / "0001"
    (round_dir / "evidence").mkdir(parents=True)
    (round_dir / "reviews").mkdir(parents=True)
    (round_dir / "scope-lock.md").write_text(
        "# Scope Lock\n\n## Allowed Changes\n\n"
        "- Write reviews under `rounds/0001/reviews/`.\n",
        encoding="utf-8",
    )
    return project


def _pr3_round_dir(project: Path) -> Path:
    return project / ".harnessloop" / "goals" / "20260101-001-pr3" / "rounds" / "0001"


def _pr3_write_review(project: Path, text: str, name: str = "review.md") -> None:
    (_pr3_round_dir(project) / "reviews" / name).write_text(text, encoding="utf-8")


def _pr3_declare(project: Path, roots_obj: dict) -> None:
    setup_dir = project / ".harnessloop" / "setup"
    setup_dir.mkdir(parents=True, exist_ok=True)
    (setup_dir / "reference-roots.json").write_text(json.dumps(roots_obj), encoding="utf-8")


def _pr3_bind(project: Path, bindings_obj: dict) -> None:
    local_dir = project / ".harnessloop" / "local"
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "reference-roots.local.json").write_text(json.dumps(bindings_obj), encoding="utf-8")


def _pr3_wiki_root(tmp_root: Path) -> Path:
    """A representative external root: `SCHEMA.md` at the top (regression
    guard for the single-`@` / `alias:` sigils this syntax replaced -- both
    silently dropped a bare top-level filename), `kernel/` and `research/`
    subdirectories.

    Returns the *canonical* (`resolve()`d) path, not the raw
    `tmp_root / "wiki"` join: `tempfile.mkdtemp()` on macOS returns a path
    under `/var/...`, and `/var` is itself a symlink to `/private/var` --
    `_load_one_root` always canonicalizes a declared root before using it
    (§2.5), so any fixture that later calls a PR-3 internal expecting an
    already-canonical domain (`_is_contained_pinned`), or compares a
    real resolved path against this fixture's own path, must use the same
    canonical form or the comparison spuriously fails on such platforms.
    """
    wiki = tmp_root / "wiki"
    (wiki / "kernel").mkdir(parents=True)
    (wiki / "research").mkdir(parents=True)
    (wiki / "SCHEMA.md").write_text("schema\n", encoding="utf-8")
    (wiki / "kernel" / "facts.md").write_text("facts\n", encoding="utf-8")
    return wiki.resolve()


def _pr3_standard_declaration(wiki_root: Path) -> dict:
    return {
        "version": 1,
        "roots": [
            {
                "alias": "wiki",
                "purpose": "external design wiki",
                "expect_present": ["SCHEMA.md", "kernel/"],
                "subpaths": ["kernel", "research"],
                "approved_by": "user-confirmed 2026-07-27",
            }
        ],
    }


def _case_fixture_class(wiki, alt) -> str:
    """Classify which of three real platform behaviors a case-swapped path
    pair (`wiki`, and `alt = wiki` with its name case-swapped) exhibits, so
    G22a can pick the correct branch. Takes anything duck-typed like a
    `Path` (needs only `str()`, `.exists()`, `.resolve()`) so G29b can drive
    all three classes from fakes on one host instead of needing three
    physically different filesystems.

    - "case-sensitive" (matches ubuntu-latest/ext4): `alt` does not exist as
      the same path at all -- the volume treats the two spellings as
      unrelated. The collision this fixture is built to reproduce is not
      constructible here; the caller must skip it honestly. (This is also
      the fallback for the degenerate case where `alt` happens to be
      spelled identically to `wiki`.)
    - "resolve-folds" (matches windows-latest): `alt` exists and names the
      same directory, but `Path.resolve()` ALSO folds the case difference
      away, so the two resolved strings already compare equal. On such a
      volume the fixture's own premise -- "grouping by Path-string equality
      could not have seen this collision" -- is false before any assertion
      about shadow-alias detection is even made, so asserting it would be
      asserting something genuinely false on this platform, not skipping a
      redundant check. The caller must skip honestly here too, but unlike
      the case-sensitive class, coverage is not lost: G24a exercises the
      same predicate (`_same_dir` seeing one directory through two unequal
      spellings) via a symlink, portably, on every platform including this
      one.
    - "usable" (matches macos-latest/APFS default): `alt` exists, names the
      same directory, and `Path.resolve()` does NOT fold the case
      difference -- the original bug reproduces end-to-end and the full
      fixture (premise + samefile + shadow-alias detection) should run.
    """
    if not (alt.exists() and str(alt) != str(wiki)):
        return "case-sensitive"
    if alt.resolve() == wiki.resolve():
        return "resolve-folds"
    return "usable"


def _classify_dotdot_symlink_resolution(resolved, outside_target, inside_target) -> str:
    """Pure classification: given an already-`.resolve()`d candidate and the
    two possible (already-resolved) landing spots for a `link/../probe.txt`
    round-trip, decide which of T-064 MUST-FIX C's two real-world platform
    semantics it matches. Split out from `_dotdot_symlink_semantics` (which
    builds the real on-disk scenario) so G30a can drive both branches from
    fabricated inputs -- anything duck-typed enough to support `==` -- on
    every platform, instead of needing two physically different
    filesystems.

    - "canonical": `resolved` is the *outside* target -- `Path.resolve()`
      followed the symlink to its real location before applying the
      trailing `..` (matches macos-latest/ubuntu-latest).
    - "lexical": `resolved` is the *inside* target (or, in the real
      probe, simply does not exist) -- `..` was erased before the symlink
      was ever consulted, so the round-trip never left the symlink's own
      lexical parent (matches windows-latest).
    - "unrecognized": neither -- a third semantics this module does not
      yet model. Callers must fail loudly on this, not silently skip.
    """
    if resolved == outside_target:
        return "canonical"
    if resolved == inside_target:
        return "lexical"
    return "unrecognized"


def _dotdot_symlink_semantics(tmp_root: Path) -> str:
    """Classify, via a real on-disk symlink + `..` round-trip (never
    `sys.platform`), whether THIS platform's path resolution treats a
    project-internal symlink pointing outside the project, cited as
    `link/../probe.txt`, canonically or lexically -- computed ONCE and
    shared by all three T-064 MUST-FIX C counterexamples below
    (`symlink_dotdot_normpath_order`: direct base x2, `.gitmodules` base
    x1) so they classify the same way instead of each re-probing (and
    risking three different verdicts about the same platform).

    Builds `inside/link -> outside/sub` (a project-internal symlink to an
    outside directory -- exactly the T-064 shape) plus a same-named probe
    file on both sides of the boundary, then resolves
    `inside/link/../probe.txt` with `Path.resolve(strict=False)` (the same
    primitive `_canonical`/`_is_contained` use) and classifies which file
    it actually lands on via `_classify_dotdot_symlink_resolution`:

    - "canonical" (matches macos-latest/ubuntu-latest): lands on
      `outside/probe.txt`. Confirmed directly from the `posixpath` source
      (`_joinrealpath`), not merely inferred: it walks the path
      component-by-component, resolving symlinks in place and applying a
      following `..` against the *already-resolved* accumulator -- exactly
      what the kernel itself does. The T-064 MUST-FIX C fixtures below
      reproduce their documented escape end-to-end on this platform.
    - "lexical" (matches windows-latest): lands on `inside/probe.txt` (or
      resolves to a nonexistent path under `inside/`). Confirmed directly
      from the `ntpath` source, not merely inferred: `ntpath.realpath`'s
      first executable statement is `path = normpath(path)` -- a pure
      string collapse with zero filesystem access -- run *before*
      `_getfinalpathname` (the actual reparse-point-following call) is
      ever reached, so a symlink fully cancelled by a matching `..` is
      erased from the string before the OS gets a chance to substitute
      it. The specific "symlink-then-`..`" shape is not constructible via
      this primitive on this platform; the fixtures below skip that
      specific shape honestly. This does NOT mean the project boundary
      itself goes unchecked here: T-063 MUST-FIX 2
      (`symlink_containment_escape`) already covers a symlink escape that
      does not involve `..` (the `link/pkg/ghost.py` fixture above, plus
      G30b below), live, on every platform -- unaffected by this
      lexical-vs-canonical distinction since there is no `..` for lexical
      processing to erase.
    - "unsupported": `os.symlink` unavailable or failed on this
      filesystem -- mirrors the existing `symlinks_supported` skip path
      used throughout this file.
    """
    if not hasattr(os, "symlink"):
        return "unsupported"
    probe_root = tmp_root / f"dotdot-semantics-probe-{uuid.uuid4().hex}"
    inside = probe_root / "inside"
    outside = probe_root / "outside"
    try:
        inside.mkdir(parents=True)
        (outside / "sub").mkdir(parents=True)
        (outside / "probe.txt").write_text("outside\n", encoding="utf-8")
        (inside / "probe.txt").write_text("inside\n", encoding="utf-8")
        try:
            (inside / "link").symlink_to(outside / "sub", target_is_directory=True)
        except (OSError, NotImplementedError):
            return "unsupported"
        resolved = (inside / "link/../probe.txt").resolve(strict=False)
        return _classify_dotdot_symlink_resolution(
            resolved,
            (outside / "probe.txt").resolve(strict=False),
            (inside / "probe.txt").resolve(strict=False),
        )
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)


def validate_protocol_gates() -> None:
    print("[7/9] Mechanical protocol gates (verify_protocol.py)")
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
            "- `docs/genuinely_missing_file.md`\n"
            "\n"
            "Mentioning the marker as quoted text must NOT act as an instruction: the marker is "
            "`<!-- verify:ignore -->` and this line also cites `docs/mentioned_not_ignored.md`\n"
            "The line after a mention-only line is likewise unaffected: `docs/after_mention.md`\n",
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
        # TH: the marker was matched as a bare substring, so a line that merely
        # *quoted* it inside a code span -- a review documenting the exemption
        # mechanism -- silently exempted every citation on that line, and on the
        # line after it. Live false green until 0.26.0.
        check(
            any("mentioned_not_ignored.md" in v["detail"] for v in violations),
            "a marker quoted inside a code span is TEXT, not an instruction -- citations on "
            "that line are still checked (substring match would have exempted them)",
        )
        check(
            any("after_mention.md" in v["detail"] for v in violations),
            "a mention-only line does not exempt the following line either -- the previous-line "
            "scope keys on active markers, not on the marker appearing anywhere in the text",
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
        "- `lib/subdir`\n"
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

    # PR-3 (external-citation-base-spec-20260727.md §2.1): an `@@<alias>/...`
    # span no longer takes the shape_dropped exit even with an
    # extension-less, no-trailing-slash tail -- this is the one behavior
    # change §2.1 explicitly calls for (branch (a): unconditionally cited).
    # Regression guard for the fact that `@@wiki/kernel` used to be this
    # module's own worked example of a shape-dropped span (PR-0/v0.18.0).
    (
        pr3_alias_cited,
        _pr3_alias_exempt,
        _pr3_alias_ignored,
        pr3_alias_shape_dropped,
        _pr3_alias_has_ignore,
    ) = verify_protocol.pathish_citations("- `@@wiki/kernel`\n")
    check(
        pr3_alias_cited == ["@@wiki/kernel"] and pr3_alias_shape_dropped == 0,
        f"PR-3: `@@wiki/kernel` (alias-shaped, extensionless tail) is unconditionally cited, "
        f"not shape-dropped (got cited={pr3_alias_cited}, shape_dropped={pr3_alias_shape_dropped})",
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
            not any("src/pkgdir" in v["detail"] or "lib/subdir" in v["detail"] for v in pr0_violations),
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

    # Computed ONCE and shared by both T-064 MUST-FIX C counterexamples below
    # (direct base and .gitmodules base) -- see `_dotdot_symlink_semantics`
    # docstring. A runtime probe, not a `sys.platform` check: this is what
    # lets the three fixtures below tell an actual, still-live escape apart
    # from a platform where the specific `..`-cancellation shape they test
    # cannot be constructed at all.
    _dotdot_semantics = _dotdot_symlink_semantics(REPO_ROOT / ".tmp")
    check(
        _dotdot_semantics in ("canonical", "lexical", "unsupported"),
        f"_dotdot_symlink_semantics returned a recognized classification (got {_dotdot_semantics!r}) "
        "-- 'unrecognized' would mean this platform's symlink-then-`..` resolution matches "
        "neither modeled semantics and the T-064 MUST-FIX C fixtures below need a human to look "
        "at this platform, not a silent skip",
    )

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
                if _dotdot_semantics == "canonical":
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
                elif _dotdot_semantics == "lexical":
                    print(
                        "  (skipped: symlink_dotdot_normpath_order direct-base counterexample -- "
                        "this platform's own path resolution treats `link/..` lexically (verified "
                        "via a live probe, `_dotdot_symlink_semantics`, not sys.platform): `..` is "
                        "erased from the string before `link` is ever recognized as a symlink, so "
                        "`link/../escape.md` never reaches through the symlink at all -- there is "
                        "no escape shape to detect here on this platform. Cross-platform coverage "
                        "is not lost: T-063 MUST-FIX 2 (symlink_containment_escape, "
                        "`link/pkg/ghost.py` above, and G30b below) still runs live on every "
                        "platform and rejects the genuinely dangerous shape -- a project-internal "
                        "symlink cited WITHOUT `..` -- which this lexical-vs-canonical distinction "
                        "does not affect.)"
                    )
                elif _dotdot_semantics == "unsupported":
                    # Rare inconsistency window: the shared probe's own (separate)
                    # symlink attempt failed even though this fixture's just succeeded.
                    # Fall back to the pre-existing honest skip rather than asserting
                    # something the probe could not classify.
                    print(
                        "  (skipped: symlinks unsupported per the shared "
                        "_dotdot_symlink_semantics probe -- symlink_dotdot_normpath_order "
                        "direct-base counterexample)"
                    )
                else:
                    check(
                        False,
                        "T-064 MUST-FIX C direct-base counterexample: _dotdot_symlink_semantics "
                        f"returned {_dotdot_semantics!r} for this platform, neither 'canonical' "
                        "nor 'lexical' -- this needs a human to look at, not a silent skip",
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
                # WOULD accept this .gitmodules path as a resolution base. Gated on
                # `_dotdot_semantics` (not the fixture below it, which stays live either
                # way -- see the "lexical" branch comment): the disagreement this
                # mutation control demonstrates is specifically `_canonical()` (which
                # goes through `Path.resolve()`) folding `smod/..` away lexically while
                # `is_dir()` follows the symlink for real. On a platform where THIS
                # module's probe classifies as "lexical" (windows-latest), Windows's own
                # path-canonicalization step already erases `smod/..` for every Win32
                # file API `Path.is_dir()`/`os.stat()` eventually calls too (not just
                # `Path.resolve()`) -- so `raw_candidate.is_dir()` is also `False` there,
                # both sides agree (safely: nothing is found, not "found and accepted"),
                # and this specific disagreement-shaped assertion does not hold, though
                # no escape happens either (see the roots/end-to-end checks below, which
                # stay live and passing on this platform for exactly that reason).
                if _dotdot_semantics == "canonical":
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
                elif _dotdot_semantics == "lexical":
                    print(
                        "  (skipped: symlink_dotdot_normpath_order .gitmodules-base mutation "
                        "control -- this platform's own path canonicalization erases `smod/..` "
                        "lexically for `is_dir()` too (verified via a live probe, "
                        "`_dotdot_symlink_semantics`, not sys.platform), so `is_dir()` and "
                        "`_canonical()` agree instead of disagreeing -- there is nothing here "
                        "for MUST-FIX C to be load-bearing against on this platform. The actual "
                        "protection (submodule_roots correctly excluding the escaping root, and "
                        "verify correctly reporting the citation dangling, both checked "
                        "unconditionally below) still holds -- just because this platform never "
                        "lets the traversal reach `outside/mod` via ANY API, not because "
                        "harnessloop's own containment check caught it here.)"
                    )
                elif _dotdot_semantics == "unsupported":
                    # Rare inconsistency window: the shared probe's own (separate)
                    # symlink attempt failed even though this fixture's just succeeded.
                    print(
                        "  (skipped: symlinks unsupported per the shared "
                        "_dotdot_symlink_semantics probe -- symlink_dotdot_normpath_order "
                        ".gitmodules-base mutation control)"
                    )
                else:
                    check(
                        False,
                        "T-064 MUST-FIX C .gitmodules-base mutation control: "
                        f"_dotdot_symlink_semantics returned {_dotdot_semantics!r} for this "
                        "platform, neither 'canonical' nor 'lexical' -- this needs a human to "
                        "look at, not a silent skip",
                    )

                # These two stay live and unconditional on every platform (unlike the
                # mutation control above): they assert the *outcome* -- root excluded,
                # citation dangling -- and that outcome holds on both semantics, just via
                # different mechanisms (canonical: containment catches it; lexical:
                # `is_dir()` never reaches through `smod` at all, so `submodule_roots`
                # never accepts the root in the first place -- see the comment above).
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

    # =====================================================================
    # G17 (external-citation-base-spec-20260727.md §3.1, PR-2 v0.20.0):
    # round-container / round-artifact symlink containment. `Path.rglob`'s
    # per-entry `is_symlink()` guard only ever sees entries *inside* a
    # directory -- structurally blind to the starting directory itself (or
    # one of its own ancestors) being a symlink escape, because the OS
    # transparently follows it the moment the walk opens it. Three real,
    # independently reproduced holes share this one blind spot:
    #   A: `reviews/ext.md` is a symlink out of the project (an ENTRY).
    #   B: `reviews/` itself is a symlink out of the project (a CONTAINER).
    #   C: `rounds/0001` itself is a symlink out of the project (a
    #      CONTAINER two levels up -- takes the whole round, scope-lock
    #      included, with it).
    # Plus a fourth, orthogonal hole: a dangling symlink's `is_file()` is
    # `False` for the same reason a genuine absence is, so a filter built on
    # `is_file()` alone (as the pre-fix `checked_files` comprehension was)
    # drops it with zero signal -- T-062 `broken_symlink` reproduced
    # identically on the artifact side.
    #
    # Each "mutation control" below reconstructs the exact pre-fix logic
    # inline (raw `rglob` + `is_file()`, `.is_dir()` alone, plain
    # `.read_text()`) using the *same on-disk fixture*, rather than loading
    # a historical copy of verify_protocol.py -- this stays meaningful
    # forever, independent of git history, exactly like this file's existing
    # T-063/T-064 mutation controls.
    # =====================================================================
    print("  G17: round artifact / container containment (PR-2, symlink escapes)")

    if not hasattr(os, "symlink"):
        print("  (skipped: os.symlink unavailable on this platform -- all G17 fixtures)")
    else:
        # -- Fixture A: reviews/ext.md is a symlink to a file outside the project.
        # Deliberately no path-shaped citation inside the external content --
        # this isolates "was the content read at all, and did Rule A notice",
        # from Rule B's own (separately, correctly working) dangling-citation
        # detection, which would otherwise confound the "0 violations before"
        # reading with an unrelated true positive.
        g17a_root = REPO_ROOT / ".tmp" / f"verify-fixture-g17a-{uuid.uuid4().hex}"
        g17a_outside = Path(tempfile.mkdtemp(prefix="harnessloop-g17a-outside-"))
        try:
            round_dir = g17a_root / ".harnessloop" / "goals" / "20260727-001-fixture" / "rounds" / "0001"
            (round_dir / "reviews").mkdir(parents=True)
            (round_dir / "evidence").mkdir(parents=True)
            (round_dir / "scope-lock.md").write_text(
                "# Scope Lock\n\n## Allowed Changes\n\n"
                "- Write evidence under `rounds/0001/evidence/`.\n"
                "- Write reviews under `rounds/0001/reviews/`.\n",
                encoding="utf-8",
            )
            (g17a_outside / "ext.md").write_text(
                "External content this project must never read. No path-shaped "
                "citations here at all.\n",
                encoding="utf-8",
            )
            ext_link = round_dir / "reviews" / "ext.md"
            ext_link.symlink_to(g17a_outside / "ext.md")

            pre_fix_reviews = [p for p in sorted((round_dir / "reviews").rglob("*")) if p.is_file()]
            check(
                ext_link in pre_fix_reviews
                and "must never read" in ext_link.read_text(encoding="utf-8"),
                "mutation control (G17 fixture A, pre-fix reconstruction): the old "
                "`rglob('*')` + `is_file()` filter (no is_symlink() check) includes "
                "the symlinked ext.md as an ordinary entry, and a plain `.read_text()` "
                "on it -- exactly what pre-fix Rule B called -- reads the real "
                "external content (confirms the escape was real, 0 violations, "
                "rule_b_files=1, before this fix)",
            )

            violations, coverage = verify_protocol.verify_project(g17a_root)
            artifact_violations = [v for v in violations if v["kind"] == "round-artifact-is-symlink"]
            check(
                len(violations) == 1
                and artifact_violations
                and str(ext_link) in artifact_violations[0]["detail"],
                f"G17 fixture A (fixed): reviews/ext.md (a symlink out of the project) "
                f"is reported round-artifact-is-symlink by name (got {violations})",
            )
            check(
                coverage.get("rule_b_files") == 0 and coverage.get("citations_checked") == 0,
                f"G17 fixture A (fixed): the symlinked entry is excluded before Rule B "
                f"ever reads it -- rule_b_files=0, citations_checked=0 (got {coverage})",
            )
        finally:
            shutil.rmtree(g17a_root, ignore_errors=True)
            shutil.rmtree(g17a_outside, ignore_errors=True)

        # -- Fixture B: reviews/ ITSELF is a symlink to a directory outside the
        # project. The assertion below is deliberately about the `reviews`
        # container itself being NAMED in a violation -- not "zero files found
        # under it", which (on this module's tested Python versions) holds
        # trivially either way, symlink guard or not, and would be a
        # false-green assertion (see verify_protocol._scan_round_artifacts'
        # docstring and the module's B2 fixture note).
        g17b_root = REPO_ROOT / ".tmp" / f"verify-fixture-g17b-{uuid.uuid4().hex}"
        g17b_outside = Path(tempfile.mkdtemp(prefix="harnessloop-g17b-outside-"))
        try:
            round_dir = g17b_root / ".harnessloop" / "goals" / "20260727-001-fixture" / "rounds" / "0001"
            round_dir.mkdir(parents=True)
            (round_dir / "evidence").mkdir(parents=True)
            (round_dir / "scope-lock.md").write_text(
                "# Scope Lock\n\n## Allowed Changes\n\n"
                "- Write evidence under `rounds/0001/evidence/`.\n"
                "- Write reviews under `rounds/0001/reviews/`.\n",
                encoding="utf-8",
            )
            (g17b_outside / "ext.md").write_text(
                "external review content, reached via a symlinked reviews/ directory\n",
                encoding="utf-8",
            )
            dlink = round_dir / "reviews"
            dlink.symlink_to(g17b_outside, target_is_directory=True)

            check(
                dlink.is_dir() and list(dlink.rglob("*.md")),
                "mutation control (G17 fixture B, pre-fix reconstruction): "
                "`reviews_dir.is_dir()` follows the container symlink (True) and "
                "`rglob('*.md')` finds the external file straight through it -- no "
                "is_symlink() check existed anywhere in this path pre-fix (confirms "
                "the escape was real, 0 violations, before this fix)",
            )

            violations, coverage = verify_protocol.verify_project(g17b_root)
            container_violations = [v for v in violations if v["kind"] == "round-container-escapes-project"]
            check(
                len(violations) == 1
                and container_violations
                and str(dlink) in container_violations[0]["detail"],
                f"G17 fixture B (fixed): the `reviews/` DIRECTORY ITSELF (a symlink "
                f"out of the project) is named in a round-container-escapes-project "
                f"violation -- not merely 'zero files under it' (got {violations})",
            )
            check(
                coverage.get("rule_b_files") == 0 and coverage.get("citations_checked") == 0,
                f"G17 fixture B (fixed): reviews/ is never enumerated once its "
                f"container check fails -- rule_b_files=0, citations_checked=0 "
                f"(got {coverage})",
            )
        finally:
            shutil.rmtree(g17b_root, ignore_errors=True)
            shutil.rmtree(g17b_outside, ignore_errors=True)

        # -- Fixture C: rounds/0001 ITSELF is a symlink to a directory outside
        # the project that holds a whole round -- scope-lock.md included, per
        # the spec's own real repro ("整轮(含 scope-lock)从项目外读入"). --
        g17c_root = REPO_ROOT / ".tmp" / f"verify-fixture-g17c-{uuid.uuid4().hex}"
        g17c_outside = Path(tempfile.mkdtemp(prefix="harnessloop-g17c-outside-"))
        try:
            (g17c_root / ".harnessloop" / "goals" / "20260727-001-fixture" / "rounds").mkdir(parents=True)
            (g17c_outside / "evidence").mkdir(parents=True)
            (g17c_outside / "reviews").mkdir(parents=True)
            (g17c_outside / "scope-lock.md").write_text(
                "# Scope Lock\n\n## Allowed Changes\n\n"
                "- Write evidence under `rounds/0001/evidence/`.\n"
                "- Write reviews under `rounds/0001/reviews/`.\n",
                encoding="utf-8",
            )
            (g17c_outside / "evidence" / "e.md").write_text("external evidence\n", encoding="utf-8")
            (g17c_outside / "reviews" / "r.md").write_text("external review\n", encoding="utf-8")
            round_link = g17c_root / ".harnessloop" / "goals" / "20260727-001-fixture" / "rounds" / "0001"
            round_link.symlink_to(g17c_outside, target_is_directory=True)

            check(
                round_link.is_dir() and (round_link / "scope-lock.md").exists(),
                "mutation control (G17 fixture C, pre-fix reconstruction): "
                "round_dir.is_dir() follows the symlinked round (True), and its "
                "scope-lock.md/evidence/reviews are all reachable straight through "
                "it -- the pre-fix `goals_dir.glob(\"*/rounds/*\")` walk would have "
                "matched and read the whole external round, scope-lock included "
                "(confirms the escape was real, 0 violations, before this fix)",
            )

            violations, coverage = verify_protocol.verify_project(g17c_root)
            container_violations = [v for v in violations if v["kind"] == "round-container-escapes-project"]
            check(
                len(violations) == 1
                and container_violations
                and str(round_link) in container_violations[0]["detail"],
                f"G17 fixture C (fixed): rounds/0001 itself (a symlink out of the "
                f"project) is named in a round-container-escapes-project violation "
                f"-- reported before verify_round ever runs on it (got {violations})",
            )
            check(
                coverage.get("rounds") == 0
                and coverage.get("rule_a_files") == 0
                and coverage.get("rule_b_files") == 0,
                f"G17 fixture C (fixed): verify_round is never invoked for the "
                f"escaping round (its scope-lock, evidence, and reviews are never "
                f"opened) -- rounds/rule_a_files/rule_b_files all stay 0 "
                f"(got {coverage})",
            )
        finally:
            shutil.rmtree(g17c_root, ignore_errors=True)
            shutil.rmtree(g17c_outside, ignore_errors=True)

        # -- Broken (dangling) symlink, standalone: proves the guard is not
        # built on top of is_file() -- a dangling symlink's is_file() is False
        # for the same reason a genuine absence is, so a filter relying on
        # is_file() alone (as pre-fix `checked_files` did) drops it with zero
        # signal (T-062 broken_symlink, reproduced identically here). --
        g17d_root = REPO_ROOT / ".tmp" / f"verify-fixture-g17d-{uuid.uuid4().hex}"
        try:
            round_dir = g17d_root / ".harnessloop" / "goals" / "20260727-001-fixture" / "rounds" / "0001"
            (round_dir / "evidence").mkdir(parents=True)
            (round_dir / "reviews").mkdir(parents=True)
            (round_dir / "scope-lock.md").write_text(
                "# Scope Lock\n\n## Allowed Changes\n\n"
                "- Write evidence under `rounds/0001/evidence/`.\n",
                encoding="utf-8",
            )
            broken = round_dir / "evidence" / "broken.md"
            broken.symlink_to(round_dir / "evidence" / "does-not-exist-target.md")

            check(
                os.path.lexists(broken) and not broken.is_file(),
                "sanity: the dangling symlink exists lexically but is_file() is "
                "False -- the exact condition that made pre-fix checked_files "
                "drop it silently",
            )
            pre_fix_checked = [p for p in sorted((round_dir / "evidence").rglob("*")) if p.is_file()]
            check(
                broken not in pre_fix_checked,
                "mutation control (broken symlink, pre-fix reconstruction): the "
                "old is_file()-filtered checked_files list silently drops the "
                "dangling symlink with zero signal (confirms 0 violations, "
                "nothing counted, before this fix)",
            )

            violations, coverage = verify_protocol.verify_project(g17d_root)
            artifact_violations = [v for v in violations if v["kind"] == "round-artifact-is-symlink"]
            check(
                len(violations) == 1
                and artifact_violations
                and str(broken) in artifact_violations[0]["detail"],
                f"broken symlink (fixed): a dangling symlink under evidence/ is "
                f"reported round-artifact-is-symlink by name, not silently dropped "
                f"(got {violations})",
            )
            check(
                coverage.get("rule_a_files") == 0,
                f"broken symlink (fixed): the dangling entry never reaches "
                f"rule_a_files (got {coverage})",
            )
        finally:
            shutil.rmtree(g17d_root, ignore_errors=True)

        # -- G17 item 3 unit teeth: is_under(...) AND _is_contained(...) must
        # both hold. AND-to-OR mutation must let fixture A's escape shape
        # through (is_under alone already true) while a genuinely
        # out-of-scope, non-escaping file is a completely different shape
        # (is_under alone already false) -- proving the two conditions each
        # do their own job, neither backing up the other. --
        g17u_root = Path(tempfile.mkdtemp(prefix="harnessloop-g17unit-"))
        g17u_outside = Path(tempfile.mkdtemp(prefix="harnessloop-g17unit-outside-"))
        try:
            reviews_dir = g17u_root / "reviews"
            reviews_dir.mkdir(parents=True)
            (g17u_outside / "ext.md").write_text("external\n", encoding="utf-8")
            ext_link = reviews_dir / "ext.md"
            ext_link.symlink_to(g17u_outside / "ext.md")

            lexically_allowed = verify_protocol.is_under(ext_link, reviews_dir)
            canonically_contained = verify_protocol._is_contained(ext_link, g17u_root)
            check(
                lexically_allowed is True and canonically_contained is False,
                f"G17 item 3 sanity: ext_link is lexically under the reviews/ span "
                f"(is_under=True) while its real target escapes the project "
                f"(_is_contained=False) -- got is_under={lexically_allowed}, "
                f"_is_contained={canonically_contained}",
            )
            check(
                (lexically_allowed and canonically_contained) is False,
                "G17 item 3: AND correctly disallows the escape (a "
                "scope-lock-violation would fire for fixture A's shape)",
            )
            check(
                (lexically_allowed or canonically_contained) is True,
                "G17 item 3 mutation: OR would incorrectly allow it (fixture A "
                "'transitions green') -- proves AND, not OR, is required here",
            )

            outside_span_file = g17u_root / "not-under-any-span.md"
            outside_span_file.write_text("real, in-project, out-of-scope-lock\n", encoding="utf-8")
            out_of_scope_lexically = verify_protocol.is_under(outside_span_file, reviews_dir)
            out_of_scope_contained = verify_protocol._is_contained(outside_span_file, g17u_root)
            check(
                out_of_scope_lexically is False and out_of_scope_contained is True,
                "sanity: an ordinary project file outside the reviews/ span is "
                "lexically disallowed but canonically contained -- the opposite "
                "combination from fixture A's shape",
            )
            check(
                (out_of_scope_lexically and out_of_scope_contained) is False,
                "G17 item 3: a genuinely out-of-scope, non-escaping file is still "
                "rejected under the real AND -- the two conditions catch two "
                "different escape shapes, neither one backing up the other",
            )
        finally:
            shutil.rmtree(g17u_root, ignore_errors=True)
            shutil.rmtree(g17u_outside, ignore_errors=True)

    # G17 whole-project zero-migration (spec §5 PR-2 acceptance: "本项目全量
    # 14 轮零变化" -- first census any existing symlink under .harnessloop/,
    # since "should be zero change" is a claim to verify, not an assumption):
    # this repo's own .harnessloop/ has zero symlinks (confirmed by `find
    # .harnessloop -type l` during this round), so running the fixed gate
    # against examples/mock-project (already asserted violation-free above)
    # is the closest in-repo proxy available to CI; the real 14-round check
    # against this outer project's own .harnessloop/ was run manually against
    # both the pre-fix and post-fix code during this round (see the round's
    # evidence/decision for the exact before/after coverage dump) since
    # REPO_ROOT.parent is this harnessloop submodule's own container project,
    # not a fixture CI can assume exists in every checkout.
    print(
        "  G17 zero-migration: examples/mock-project already asserted violation-free "
        "above; this project's own 14 real rounds were compared before/after manually "
        "(see round evidence) since REPO_ROOT.parent is not a fixture."
    )

    # =========================================================================
    # PR-3 (external-citation-base-spec-20260727.md §2-3, v0.21.0; §2.4 shadow-alias guard added v0.22.0): external
    # reference roots. G1-G16, G19, G20 below. Every fixture is a fresh
    # `tempfile.mkdtemp()` tree (never `~`, never a hardcoded real host
    # directory -- G4's own use of the live `Path.home()` value is the one
    # deliberate exception, since that rule is defined against it). Mutation
    # controls never delete a real call in the shipped module (that would
    # NameError every other fixture into a false red); each reconstructs the
    # pre-fix logic as an isolated local function and calls it directly.
    print("  PR-3: external reference roots")

    print("  G1: reference-roots.json schema validation (all-or-nothing)")
    g1_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g1-"))
    try:
        project = _pr3_project(g1_root)

        def _g1_case(label: str, text: str) -> None:
            setup_dir = project / ".harnessloop" / "setup"
            setup_dir.mkdir(parents=True, exist_ok=True)
            (setup_dir / "reference-roots.json").write_text(text, encoding="utf-8")
            roots, violations = verify_protocol.load_reference_roots(project)
            check(
                roots == {} and any(v["kind"] == "reference-roots-invalid" for v in violations),
                f"G1 ({label}): invalid declaration loads zero roots and reports reference-roots-invalid",
            )

        _g1_case("invalid JSON", "{not valid json")
        _g1_case("version missing", json.dumps({"roots": []}))
        _g1_case("version wrong", json.dumps({"version": 2, "roots": []}))
        _g1_case("unknown top-level key", json.dumps({"version": 1, "roots": [], "extra": 1}))
        _g1_case(
            "unknown root key (include)",
            json.dumps(
                {
                    "version": 1,
                    "roots": [
                        {
                            "alias": "wiki",
                            "purpose": "p",
                            "expect_present": ["SCHEMA.md"],
                            "approved_by": "x",
                            "include": "other.json",
                        }
                    ],
                }
            ),
        )
        _g1_case(
            "alias grammar (uppercase)",
            json.dumps(
                {
                    "version": 1,
                    "roots": [
                        {"alias": "Wiki", "purpose": "p", "expect_present": ["SCHEMA.md"], "approved_by": "x"}
                    ],
                }
            ),
        )
        _g1_case(
            "alias collides with PATHISH_PREFIXES token",
            json.dumps(
                {
                    "version": 1,
                    "roots": [
                        {"alias": "state", "purpose": "p", "expect_present": ["SCHEMA.md"], "approved_by": "x"}
                    ],
                }
            ),
        )
        _g1_case(
            "duplicate alias",
            json.dumps(
                {
                    "version": 1,
                    "roots": [
                        {"alias": "wiki", "purpose": "p", "expect_present": ["SCHEMA.md"], "approved_by": "x"},
                        {"alias": "wiki", "purpose": "p2", "expect_present": ["SCHEMA.md"], "approved_by": "x"},
                    ],
                }
            ),
        )
        _g1_case(
            "more than 8 roots",
            json.dumps(
                {
                    "version": 1,
                    "roots": [
                        {
                            "alias": f"root{i}",
                            "purpose": "p",
                            "expect_present": ["SCHEMA.md"],
                            "approved_by": "x",
                        }
                        for i in range(9)
                    ],
                }
            ),
        )
        _g1_case(
            "file exceeds 64 KiB",
            json.dumps(
                {
                    "version": 1,
                    "roots": [
                        {
                            "alias": "wiki",
                            "purpose": "p" * 70000,
                            "expect_present": ["SCHEMA.md"],
                            "approved_by": "x",
                        }
                    ],
                }
            ),
        )

        # Mutation control: two roots declared, only the SECOND is malformed
        # -- the whole file must still load ZERO roots, not "the first one".
        (project / ".harnessloop" / "setup" / "reference-roots.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "roots": [
                        {"alias": "wiki", "purpose": "p", "expect_present": ["SCHEMA.md"], "approved_by": "x"},
                        {"alias": "BAD", "purpose": "p", "expect_present": ["SCHEMA.md"], "approved_by": "x"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        roots, violations = verify_protocol.load_reference_roots(project)
        check(
            roots == {}
            and len([v for v in violations if v["kind"] == "reference-roots-invalid"]) == 1,
            "G1 mutation control: one malformed root among several invalidates the WHOLE "
            "file (zero roots loaded), not just the bad entry ('partial load' must not happen)",
        )
    finally:
        shutil.rmtree(g1_root, ignore_errors=True)

    print("  G2: local binding forbidden keys (low-trust file cannot self-certify identity)")
    g2_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g2-"))
    try:
        project = _pr3_project(g2_root)
        wiki = g2_root / "wiki"
        _pr3_declare(project, _pr3_standard_declaration(wiki))
        for forbidden_key, forbidden_value in (
            ("identity", "verified"),
            ("available", True),
            ("optional", True),
            ("expect_present", ["x"]),
        ):
            _pr3_bind(
                project,
                {"version": 1, "bindings": {"wiki": {"path": str(wiki), forbidden_key: forbidden_value}}},
            )
            roots, violations = verify_protocol.load_reference_roots(project)
            check(
                any(v["kind"] == "reference-root-local-invalid" for v in violations)
                and roots["wiki"].unavailable_reason == "unbound",
                f"G2 ({forbidden_key}): local binding claiming '{forbidden_key}' is rejected "
                "(reference-root-local-invalid); alias falls back to unbound, not trusted",
            )

        # Mutation control: a loose loader that only checks for a 'path' key,
        # ignoring every other key -- would have silently accepted the same
        # 'available' self-claim.
        def _loose_load_local_bindings(bindings_obj: dict) -> dict:
            bindings = {}
            for alias, binding in bindings_obj.get("bindings", {}).items():
                if isinstance(binding, dict) and isinstance(binding.get("path"), str):
                    bindings[alias] = binding["path"]
            return bindings

        loose_obj = {"version": 1, "bindings": {"wiki": {"path": str(wiki), "available": True}}}
        check(
            _loose_load_local_bindings(loose_obj).get("wiki") == str(wiki),
            "G2 mutation control: a loose loader checking only for 'path' would have silently "
            "accepted the 'available' self-claim (proves the real check has teeth)",
        )
    finally:
        shutil.rmtree(g2_root, ignore_errors=True)

    print("  G3: loader never follows include/extends/relative-file-reference (opens only its own literal path)")
    g3_versioned_src = inspect.getsource(verify_protocol._load_versioned_roots)
    g3_local_src = inspect.getsource(verify_protocol._load_local_bindings)
    check(
        "include" not in g3_versioned_src.lower()
        and "extends" not in g3_versioned_src.lower()
        and "include" not in g3_local_src.lower()
        and "extends" not in g3_local_src.lower(),
        "G3: neither loader's source contains any include/extends-following logic",
    )
    check(
        g3_versioned_src.count(".read_text(") == 1 and g3_local_src.count(".read_text(") == 1,
        "G3: each loader calls .read_text() exactly once, against its own path parameter "
        "-- no indirection to a second file",
    )
    # An "include" key in a root entry is caught by the same unknown-key
    # rejection G1 already exercises above -- this is the structural
    # guarantee that makes that outcome true rather than incidental.

    print("  G4: forbidden canonical roots (checked on canonical values, never the literal declared string)")
    g4_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g4-"))
    try:
        project = _pr3_project(g4_root)
        _pr3_declare(project, _pr3_standard_declaration(g4_root / "wiki"))

        def _g4_case(label: str, raw_path: str) -> None:
            _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": raw_path}}})
            roots, violations = verify_protocol.load_reference_roots(project)
            check(
                roots["wiki"].unavailable_reason == "rejected"
                and any(v["kind"] == "reference-root-rejected" for v in violations),
                f"G4 ({label}): forbidden root is rejected",
            )

        _g4_case("filesystem root", str(Path(project.anchor)))
        _g4_case("home directory", str(Path.home()))
        _g4_case("home's parent", str(Path.home().parent))
        _g4_case("project ancestor", str(project.parent))
        _g4_case("inside the project", str(project))
        _g4_case("glob character in declared path", str(g4_root) + "/wi*ki")

        if hasattr(os, "symlink"):
            fakehome = g4_root / "fakehome"
            fakehome.mkdir()
            (fakehome / "w2").symlink_to(project.parent, target_is_directory=True)
            raw_declared = str(fakehome / "w2")
            _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": raw_declared}}})
            roots, violations = verify_protocol.load_reference_roots(project)
            check(
                roots["wiki"].unavailable_reason == "rejected",
                "G4 (symlink-to-project-ancestor): a literal declared path with no forbidden "
                "substring, whose canonical resolution IS the project's own parent, is still rejected",
            )
            check(
                raw_declared
                not in (str(project.parent), str(Path.home()), str(Path(project.anchor))),
                "G4 mutation control: the raw declared string itself matches none of the "
                "forbidden literals -- only canonical resolution (Path.resolve() following "
                "the symlink) exposes the escape; checking literal strings alone would miss it",
            )
        else:
            print("  (skipped: os.symlink unavailable on this platform)")
    finally:
        shutil.rmtree(g4_root, ignore_errors=True)

    print("  G5: unresolvable root (symlink loop) -> reference-root-unresolvable")
    g5_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g5-"))
    try:
        project = _pr3_project(g5_root)
        _pr3_declare(project, _pr3_standard_declaration(g5_root / "wiki"))
        if hasattr(os, "symlink"):
            loop_a = g5_root / "loop-a"
            loop_b = g5_root / "loop-b"
            loop_a.symlink_to(loop_b)
            loop_b.symlink_to(loop_a)
            _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(loop_a)}}})
            roots, violations = verify_protocol.load_reference_roots(project)
            check(
                roots["wiki"].unavailable_reason == "unresolvable"
                and any(v["kind"] == "reference-root-unresolvable" for v in violations),
                "G5: a symlink loop is reported reference-root-unresolvable, not silently "
                "treated as available",
            )

            def _g5_mutant_resolve_no_guard(raw: str) -> Path:
                # Pre-fix reconstruction: the same resolve call WITHOUT the
                # real code's try/except(OSError, RuntimeError).
                return Path(raw).expanduser().resolve(strict=True)

            g5_mutant_raised = False
            try:
                _g5_mutant_resolve_no_guard(str(loop_a))
            except (OSError, RuntimeError):
                g5_mutant_raised = True
            check(
                g5_mutant_raised,
                "G5 mutation control: without the try/except(OSError, RuntimeError) guard, "
                "resolving the same symlink loop raises uncaught -- proves the guard is what "
                "turns this into a clean violation rather than a crash",
            )
        else:
            print("  (skipped: os.symlink unavailable on this platform)")
    finally:
        shutil.rmtree(g5_root, ignore_errors=True)

    print("  G6: identity sentinel (expect_present) -- 'same name, different tree' must not pass")
    g6_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g6-"))
    try:
        project = _pr3_project(g6_root)
        wiki = _pr3_wiki_root(g6_root)
        _pr3_declare(project, _pr3_standard_declaration(wiki))
        _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki)}}})
        roots, violations = verify_protocol.load_reference_roots(project)
        check(
            roots["wiki"].available and not violations,
            "G6: a root whose declared expect_present sentinels genuinely exist is available",
        )

        decoy = g6_root / "decoy-tree"
        (decoy / "kernel").mkdir(parents=True)
        (decoy / "kernel" / "facts.md").write_text("not the real wiki\n", encoding="utf-8")
        _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(decoy)}}})
        roots, violations = verify_protocol.load_reference_roots(project)
        check(
            roots["wiki"].unavailable_reason == "identity-mismatch"
            and any(v["kind"] == "reference-root-identity-mismatch" for v in violations),
            "G6: a decoy tree missing a declared expect_present sentinel (SCHEMA.md) is "
            "rejected as identity-mismatch, not silently treated as the declared root",
        )

        roots_no_verify, _ = verify_protocol.load_reference_roots(project, verify_identity=False)
        check(
            roots_no_verify["wiki"].available,
            "G6 mutation control: with verify_identity=False (sentinel check skipped), the "
            "exact same decoy tree is wrongly treated as available -- proves the sentinel "
            "check itself (not just 'some check') is load-bearing",
        )
    finally:
        shutil.rmtree(g6_root, ignore_errors=True)

    print(
        "  G7: unavailable root -> external-root-unavailable (once) + "
        "external-citation-unverifiable (per citation)"
    )
    g7_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g7-"))
    try:
        project = _pr3_project(g7_root)
        _pr3_declare(project, _pr3_standard_declaration(g7_root / "wiki"))
        # Deliberately not bound -- .harnessloop/local/reference-roots.local.json
        # does not exist at all.
        _pr3_write_review(
            project,
            "Citing the external wiki twice:\n"
            "- `@@wiki/kernel/facts.md`\n"
            "- `@@wiki/research/notes.md`\n",
        )
        violations, coverage = verify_protocol.verify_project(project)
        kinds = [v["kind"] for v in violations]
        check(
            kinds.count("external-root-unavailable") == 1,
            f"G7: exactly one external-root-unavailable violation regardless of citation "
            f"count (got {kinds.count('external-root-unavailable')})",
        )
        check(
            kinds.count("external-citation-unverifiable") == 2,
            f"G7: one external-citation-unverifiable per citation (got "
            f"{kinds.count('external-citation-unverifiable')})",
        )
        check(
            coverage["external_citations_unverifiable"] == 2
            and coverage["external_citations_checked"] == 2,
            "G7: coverage counts both unverifiable citations",
        )

        def _g7_mutant_count(roots: dict, cited_list: list[str]) -> int:
            count = 0
            for cited in cited_list:
                m = verify_protocol.ALIAS_CITATION_RE.match(cited)
                if m and m.group(1) in roots:
                    root = roots[m.group(1)]
                    if not root.available:
                        continue  # BUG: silently skip instead of reporting
                    count += 1
            return count

        mutant_roots, _ = verify_protocol.load_reference_roots(project)
        mutant_unverifiable = _g7_mutant_count(
            mutant_roots, ["@@wiki/kernel/facts.md", "@@wiki/research/notes.md"]
        )
        check(
            mutant_unverifiable == 0,
            "G7 mutation control: a 'continue instead of report' implementation would "
            "silently produce ZERO unverifiable violations for the same two citations "
            "(proves the real per-citation reporting is load-bearing noise, not decoration)",
        )
    finally:
        shutil.rmtree(g7_root, ignore_errors=True)

    print("  G8: malformed relpath (leading /, ~, drive, or .. segment) -> external-citation-rejected")
    g8_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g8-"))
    try:
        project = _pr3_project(g8_root)
        wiki = _pr3_wiki_root(g8_root)
        _pr3_declare(project, _pr3_standard_declaration(wiki))
        _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki)}}})
        root_obj = verify_protocol.load_reference_roots(project)[0]["wiki"]

        for label, rel in (
            ("absolute", "/etc/passwd"),
            ("home-relative", "~/x.md"),
            ("windows drive", "C:/x.ini"),
            ("dotdot traversal", "../../etc/passwd.conf"),
        ):
            outcome, _real = verify_protocol.resolve_external_citation(root_obj, rel)
            check(outcome == "rejected", f"G8 ({label}): `@@wiki/{rel}` is rejected")

        _pr3_write_review(project, "- `@@wiki/../../etc/passwd.conf`\n")
        violations, coverage = verify_protocol.verify_project(project)
        check(
            any(v["kind"] == "external-citation-rejected" for v in violations)
            and coverage["external_citations_rejected"] == 1,
            "G8 end-to-end: a `..`-traversal alias citation is rejected through verify_project",
        )

        def _g8_mutant_resolve_in_root_no_defense1(root: Path, rel: str) -> Path | None:
            candidate = root / rel  # skips the literal prefix/`..`-segment check entirely
            if not verify_protocol._is_contained_pinned(candidate, root):
                return None
            return candidate

        mutant_candidate = _g8_mutant_resolve_in_root_no_defense1(wiki, "~/x.md")
        check(
            mutant_candidate is not None,
            "G8 mutation control: without defense 1, '~/x.md' is NOT caught by containment "
            "alone -- pathlib treats a leading '~' as a literal directory NAME (not "
            "home-expansion), so `root/'~'/x.md` stays canonically inside root; it would be "
            "misreported as not_found instead of rejected without the explicit prefix check",
        )
    finally:
        shutil.rmtree(g8_root, ignore_errors=True)

    print("  G9: unfolded raw join (never os.path.normpath-folded) before pinned containment")
    g9_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g9-"))
    try:
        project = _pr3_project(g9_root)
        wiki = _pr3_wiki_root(g9_root)
        outside = g9_root / "outside"
        outside.mkdir()
        (wiki / "escape.md").write_text("DECOY -- must never be the resolved target\n", encoding="utf-8")
        if hasattr(os, "symlink"):
            (wiki / "link").symlink_to(outside, target_is_directory=True)
            _pr3_declare(project, _pr3_standard_declaration(wiki))
            _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki)}}})
            root_obj = verify_protocol.load_reference_roots(project)[0]["wiki"]

            outcome, _real = verify_protocol.resolve_external_citation(root_obj, "link/../escape.md")
            check(
                outcome == "rejected",
                "G9: `@@wiki/link/../escape.md` (link is a symlink pointing outside wiki, and "
                "a same-named decoy exists inside wiki) is rejected -- the real target is "
                "where `link` actually points, not the coincidental decoy",
            )

            def _g9_mutant_resolve_in_root(root: Path, rel: str) -> Path | None:
                candidate = Path(os.path.normpath(str(root / rel)))
                if not verify_protocol._is_contained_pinned(candidate, root):
                    return None
                return candidate

            mutant_candidate = _g9_mutant_resolve_in_root(wiki, "link/../escape.md")
            check(
                mutant_candidate is not None and mutant_candidate == wiki / "escape.md",
                "G9 mutation control: normpath-folding before containment resolves to the "
                "exact decoy path `wiki/escape.md` and wrongly accepts it (proves the real "
                "code's raw-unfolded-join discipline is load-bearing, not just 'some "
                "containment check')",
            )

            outcome2, real2 = verify_protocol.resolve_external_citation(root_obj, "kernel/facts.md")
            check(
                outcome2 == "resolved" and real2 == wiki / "kernel" / "facts.md",
                "G9 positive control: a genuine citation resolves to the exact expected "
                "path, not merely a truthy verdict",
            )
        else:
            print("  (skipped: os.symlink unavailable on this platform)")
    finally:
        shutil.rmtree(g9_root, ignore_errors=True)

    print("  G10: exact case-sensitive segment matching (host filesystem case-folding must not leak in)")
    g10_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g10-"))
    try:
        project = _pr3_project(g10_root)
        wiki = _pr3_wiki_root(g10_root)
        _pr3_declare(project, _pr3_standard_declaration(wiki))
        _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki)}}})
        root_obj = verify_protocol.load_reference_roots(project)[0]["wiki"]

        outcome, _real = verify_protocol.resolve_external_citation(root_obj, "kernel/facts.md")
        check(outcome == "resolved", "G10: the correctly-cased citation resolves")

        outcome, _real = verify_protocol.resolve_external_citation(root_obj, "KERNEL/FACTS.MD")
        check(
            outcome == "not_found",
            "G10: a wrong-cased citation (`KERNEL/FACTS.MD` for real `kernel/facts.md`) is "
            "not_found, not resolved -- exact segment matching, host-filesystem-independent",
        )

        case_insensitive_fs = (wiki / "KERNEL").exists()
        if case_insensitive_fs:
            candidate = wiki / "KERNEL" / "FACTS.MD"
            check(
                candidate.exists(),
                "G10 mutation control: plain Path.exists() on the wrong-cased path DOES "
                "resolve on this (case-insensitive) filesystem -- proves the real code's "
                "exact os.scandir walk, not just 'some existence check', is what keeps this "
                "a not_found",
            )
        else:
            print(
                "  (G10 mutation control skipped: host filesystem is case-sensitive -- "
                "naive Path.exists() would already reject the wrong case here too)"
            )
    finally:
        shutil.rmtree(g10_root, ignore_errors=True)

    print("  G11: trailing-slash directory semantics and broken symlink -> external-citation-not-found")
    g11_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g11-"))
    try:
        project = _pr3_project(g11_root)
        wiki = _pr3_wiki_root(g11_root)
        _pr3_declare(project, _pr3_standard_declaration(wiki))
        _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki)}}})
        root_obj = verify_protocol.load_reference_roots(project)[0]["wiki"]

        outcome, _real = verify_protocol.resolve_external_citation(root_obj, "kernel/facts.md/")
        check(outcome == "not_found", "G11: `@@wiki/kernel/facts.md/` (file cited as a directory) is not_found")

        outcome, _real = verify_protocol.resolve_external_citation(root_obj, "kernel/")
        check(outcome == "resolved", "G11: `@@wiki/kernel/` (a real directory) resolves")

        if hasattr(os, "symlink"):
            (wiki / "broken").symlink_to(wiki / "does-not-exist.md")
            outcome, _real = verify_protocol.resolve_external_citation(root_obj, "broken")
            check(
                outcome == "not_found",
                "G11: a broken symlink inside the root is not_found, not resolved",
            )
            with os.scandir(wiki) as it:
                scandir_names = {e.name for e in it}
            check(
                "broken" in scandir_names,
                "G11 mutation control: os.scandir alone DOES list the broken symlink's "
                "dirent -- proves the follow-on existence/type check (not scandir alone) is "
                "what turns this into not_found",
            )
        else:
            print("  (skipped: os.symlink unavailable on this platform)")
    finally:
        shutil.rmtree(g11_root, ignore_errors=True)

    print("  G12: subpaths whitelist applies to the CANONICAL relative path, not the literal one")
    g12_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g12-"))
    try:
        project = _pr3_project(g12_root)
        wiki = _pr3_wiki_root(g12_root)
        (wiki / "raw").mkdir()  # not in the subpaths whitelist
        (wiki / "raw" / "x.md").write_text("raw content\n", encoding="utf-8")
        if hasattr(os, "symlink"):
            (wiki / "kernel" / "link").symlink_to(wiki / "raw", target_is_directory=True)
            _pr3_declare(project, _pr3_standard_declaration(wiki))  # subpaths=["kernel","research"]
            _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki)}}})
            root_obj = verify_protocol.load_reference_roots(project)[0]["wiki"]

            outcome, _real = verify_protocol.resolve_external_citation(root_obj, "kernel/link/x.md")
            check(
                outcome == "rejected",
                "G12: `@@wiki/kernel/link/x.md` -- literal first segment 'kernel' is "
                "whitelisted, but kernel/link is a symlink into raw/ (not whitelisted); the "
                "canonical relative path is judged, and it is rejected",
            )

            first_seg_literal = "kernel/link/x.md".split("/")[0]
            check(
                first_seg_literal in (root_obj.subpaths or ()),
                "G12 mutation control: the LITERAL first segment ('kernel') IS in the "
                "whitelist -- proves judging subpaths against the literal segment (instead "
                "of the canonical-relative one) would have wrongly accepted this",
            )

            outcome, real = verify_protocol.resolve_external_citation(root_obj, "kernel/facts.md")
            check(
                outcome == "resolved" and real == wiki / "kernel" / "facts.md",
                "G12: a genuine, non-symlinked in-whitelist citation still resolves",
            )
        else:
            print("  (skipped: os.symlink unavailable on this platform)")
    finally:
        shutil.rmtree(g12_root, ignore_errors=True)

    print(
        "  G13 (alias-only, load-bearing): declaring 'wiki' must NOT make a bare "
        "project-relative prefix resolve against it -- end-to-end fixture"
    )
    g13_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g13-"))
    try:
        project = _pr3_project(g13_root)
        wiki = _pr3_wiki_root(g13_root)
        _pr3_declare(project, _pr3_standard_declaration(wiki))
        _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki)}}})
        # Bare prefix, no `@@` sigil -- must remain dangling even though
        # 'kernel/facts.md' genuinely exists under the declared+bound root.
        _pr3_write_review(project, "- `kernel/facts.md`\n")
        violations, coverage = verify_protocol.verify_project(project)
        check(
            any(
                v["kind"] == "dangling-citation" and "kernel/facts.md" in v["detail"]
                for v in violations
            ),
            "G13: `kernel/facts.md` (bare prefix, no @@ sigil) still reports dangling-citation "
            "even though the declared+available 'wiki' root genuinely contains it",
        )
        check(
            coverage["external_citations_checked"] == 0,
            "G13: the bare-prefix citation above never entered the external-citation counters",
        )

        def _g13_mutant_naive_exists(bases: list, cited: str) -> bool:
            # Pre-fix reconstruction of the rejected design: fold the bound
            # root into the resolution base list and just check existence.
            for base in bases:
                if (base / cited).exists():
                    return True
            return False

        mutant_roots, _ = verify_protocol.load_reference_roots(project)
        mutant_bases = [project] + [r.canonical for r in mutant_roots.values() if r.available]
        check(
            _g13_mutant_naive_exists(mutant_bases, "kernel/facts.md"),
            "G13 mutation control: folding the bound root into the resolution base list (an "
            "alternative, rejected design) WOULD resolve the bare prefix -- proves keeping "
            "the two domains structurally separate is load-bearing",
        )
    finally:
        shutil.rmtree(g13_root, ignore_errors=True)

    print(
        "  G14: external roots never enter build_suffix_index (monkeypatch-verified, "
        "not just 'the function is unchanged')"
    )
    g14_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g14-"))
    try:
        project = _pr3_project(g14_root)
        wiki = _pr3_wiki_root(g14_root)
        _pr3_declare(project, _pr3_standard_declaration(wiki))
        _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki)}}})

        touched: list[str] = []
        real_resolve = Path.resolve
        real_walk = os.walk
        real_run = subprocess.run

        def _tracking_resolve(self, *a, **kw):
            touched.append(str(self))
            return real_resolve(self, *a, **kw)

        def _tracking_walk(top, *a, **kw):
            touched.append(str(top))
            return real_walk(top, *a, **kw)

        def _tracking_run(popenargs, *a, **kw):
            if kw.get("cwd"):
                touched.append(str(kw["cwd"]))
            touched.append(str(popenargs))
            return real_run(popenargs, *a, **kw)

        Path.resolve = _tracking_resolve
        os.walk = _tracking_walk
        subprocess.run = _tracking_run
        try:
            verify_protocol.build_suffix_index(project)
        finally:
            Path.resolve = real_resolve
            os.walk = real_walk
            subprocess.run = real_run

        wiki_markers = (str(wiki), str(wiki.resolve()))
        offending = [p for p in touched if any(m in p for m in wiki_markers)]
        check(
            not offending,
            f"G14: build_suffix_index makes zero Path.resolve/os.walk/subprocess.run calls "
            f"targeting the declared reference root (offending sample: {offending[:5]})",
        )
    finally:
        shutil.rmtree(g14_root, ignore_errors=True)

    print("  G15: undeclared alias falls back to unchanged project-domain judgment (zero-migration invariant)")
    g15_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g15-"))
    try:
        project_no_decl = _pr3_project(g15_root / "no-decl")
        _pr3_write_review(project_no_decl, "- `@@foo/bar.md`\n- `does/not/exist.md`\n")
        violations_before, _cov_before = verify_protocol.verify_project(project_no_decl)

        project_decl = _pr3_project(g15_root / "with-decl")
        wiki2 = _pr3_wiki_root(g15_root / "wiki-for-g15")
        _pr3_declare(project_decl, _pr3_standard_declaration(wiki2))
        _pr3_bind(project_decl, {"version": 1, "bindings": {"wiki": {"path": str(wiki2)}}})
        _pr3_write_review(project_decl, "- `@@foo/bar.md`\n- `does/not/exist.md`\n")
        violations_after, coverage_after = verify_protocol.verify_project(project_decl)

        kinds_before = sorted(v["kind"] for v in violations_before)
        kinds_after = sorted(v["kind"] for v in violations_after)
        check(
            kinds_before == kinds_after == ["dangling-citation", "dangling-citation"],
            f"G15: `@@foo/bar.md` (undeclared alias 'foo') produces the same dangling-citation "
            f"kind whether or not an UNRELATED alias ('wiki') is declared elsewhere "
            f"(before={kinds_before}, after={kinds_after})",
        )
        check(
            any(
                "@@foo" in v["detail"] and "not a declared reference-root alias" in v["detail"]
                for v in violations_after
            ),
            "G15: the undeclared-alias hint text is present (display-only, does not change the kind)",
        )
        check(
            coverage_after["external_citations_checked"] == 0,
            "G15: an undeclared alias never enters the external_citations_* counters",
        )
    finally:
        shutil.rmtree(g15_root, ignore_errors=True)

    print(
        "  G16: declaring+binding an alias changes NOTHING for a corpus with zero @@ spans "
        "(synthetic stand-in; see report for the real .hopper/handoffs measurement)"
    )
    g16_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g16-"))
    try:
        project = g16_root / "project"
        round_dir = project / ".harnessloop" / "goals" / "20260101-001-g16" / "rounds" / "0001"
        (round_dir / "evidence").mkdir(parents=True)
        (round_dir / "reviews").mkdir(parents=True)
        (round_dir / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n- Write reviews under `rounds/0001/reviews/`.\n",
            encoding="utf-8",
        )
        (project / "src").mkdir()
        (project / "src" / "real.py").write_text("x = 1\n", encoding="utf-8")
        for i in range(8):
            (round_dir / "reviews" / f"review-{i}.md").write_text(
                f"Review {i}:\n"
                "- `src/real.py:1-2`\n"
                f"- `src/does-not-exist-{i}.py`\n"
                "- `~/.llm-wiki/agent-app-design/kernel/x.md`\n"
                "- `docs.python.org/3/library/os.html`\n",
                encoding="utf-8",
            )
        violations_before, _cov_before = verify_protocol.verify_project(project)
        dangling_before = sorted(v["detail"] for v in violations_before if v["kind"] == "dangling-citation")

        wiki3 = _pr3_wiki_root(g16_root / "wiki-for-g16")
        _pr3_declare(project, _pr3_standard_declaration(wiki3))
        _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki3)}}})
        violations_after, _cov_after = verify_protocol.verify_project(project)
        dangling_after = sorted(v["detail"] for v in violations_after if v["kind"] == "dangling-citation")

        check(
            len(dangling_before) == 8 and dangling_before == dangling_after,
            f"G16: declaring+binding 'wiki' does not change the dangling-citation count or "
            f"detail text for a corpus with zero @@ spans (before={len(dangling_before)}, "
            f"after={len(dangling_after)})",
        )
    finally:
        shutil.rmtree(g16_root, ignore_errors=True)

    print("  G19: no escape knob (argparse) and no optional/required key in either schema")
    vp_source = inspect.getsource(verify_protocol)
    forbidden_flag_pat = re.compile(r"--(allow-missing|skip-roots|no-external)\w*")
    check(
        not forbidden_flag_pat.search(vp_source),
        "G19: verify_protocol.py's argparse defines no allow-missing/skip-roots/no-external option",
    )
    check(
        "optional" not in verify_protocol._VERSIONED_ROOT_ALLOWED_KEYS
        and "required" not in verify_protocol._VERSIONED_ROOT_ALLOWED_KEYS,
        "G19: the versioned-root schema's allowed key set has no optional/required key",
    )
    check(
        "optional" not in verify_protocol._LOCAL_BINDING_ALLOWED_KEYS
        and "required" not in verify_protocol._LOCAL_BINDING_ALLOWED_KEYS,
        "G19: the local-binding schema's allowed key set has no optional/required key",
    )

    print("  G20: violation detail / coverage line / default --json never leak a reference root's local path")
    g20_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g20-"))
    try:
        new_kinds = {
            "reference-roots-invalid",
            "reference-root-local-invalid",
            "reference-root-rejected",
            "reference-root-unresolvable",
            "reference-root-identity-mismatch",
            "external-root-unavailable",
            "external-citation-unverifiable",
            "external-citation-rejected",
            "external-citation-not-found",
            "scope-lock-span-names-reference-root",
        }

        def _g20_leaks_root(text: str, wiki_path: Path) -> bool:
            return str(wiki_path) in text or "~/" in text or str(Path.home()) in text

        def _g20_scenario(label: str, project: Path, wiki_path: Path, review_text: str, bind: bool) -> set:
            _pr3_declare(project, _pr3_standard_declaration(wiki_path))
            if bind:
                _pr3_bind(project, {"version": 1, "bindings": {"wiki": {"path": str(wiki_path)}}})
            _pr3_write_review(project, review_text)

            violations, coverage = verify_protocol.verify_project(project)
            seen = {v["kind"] for v in violations}
            for v in violations:
                if v["kind"] in new_kinds:
                    check(
                        not _g20_leaks_root(v["detail"], wiki_path),
                        f"G20 ({label}): {v['kind']} detail carries no reference-root path or "
                        f"home fragment (detail={v['detail']!r})",
                    )
            check(
                not _g20_leaks_root(json.dumps(coverage), wiki_path),
                f"G20 ({label}): coverage dict carries no reference-root path or home fragment",
            )
            for use_json in (False, True):
                args = [sys.executable, str(LOOP_SCRIPTS / "verify_protocol.py"), "--project", str(project)]
                if use_json:
                    args.append("--json")
                result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
                check(
                    str(wiki_path) not in result.stdout,
                    f"G20 ({label}, {'--json' if use_json else 'human'}): stdout does not "
                    "contain the reference root's absolute local path",
                )
            return seen

        project_a = _pr3_project(g20_root / "a")
        wiki_a = _pr3_wiki_root(g20_root / "wiki-a")
        seen_a = _g20_scenario("unavailable", project_a, wiki_a, "- `@@wiki/kernel/facts.md`\n", bind=False)

        project_b = _pr3_project(g20_root / "b")
        wiki_b = _pr3_wiki_root(g20_root / "wiki-b")
        seen_b = _g20_scenario(
            "rejected", project_b, wiki_b, "- `@@wiki/../../etc/passwd.conf`\n", bind=True
        )

        check(
            {"external-root-unavailable", "external-citation-unverifiable"} <= seen_a
            and "external-citation-rejected" in seen_b,
            f"G20 fixture sanity: both scenarios exercise the intended leak-risk violation "
            f"kinds (a={sorted(seen_a)}, b={sorted(seen_b)})",
        )

        result = subprocess.run(
            [sys.executable, str(LOOP_SCRIPTS / "verify_protocol.py"), "--project", str(project_b), "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        parsed = json.loads(result.stdout)
        check(
            set(parsed["coverage"].keys()) == set(verify_protocol._empty_coverage().keys()),
            "G20: --json coverage object has exactly the whitelisted key set",
        )
        check(
            all(set(v.keys()) == {"round", "kind", "detail"} for v in parsed["violations"]),
            "G20: every --json violation entry has exactly round/kind/detail keys",
        )
    finally:
        shutil.rmtree(g20_root, ignore_errors=True)

    print("  PR-3 zero-migration: --show-root-paths runs without affecting exit code, violations, or coverage")
    g0_root = Path(tempfile.mkdtemp(prefix="hl-pr3-showpaths-"))
    try:
        project = _pr3_project(g0_root)
        result_plain = subprocess.run(
            [sys.executable, str(LOOP_SCRIPTS / "verify_protocol.py"), "--project", str(project), "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        result_show = subprocess.run(
            [
                sys.executable,
                str(LOOP_SCRIPTS / "verify_protocol.py"),
                "--project",
                str(project),
                "--json",
                "--show-root-paths",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        check(
            result_plain.returncode == result_show.returncode
            and json.loads(result_plain.stdout) == json.loads(result_show.stdout),
            "G19/G20 sanity: --show-root-paths has zero effect on exit code or --json output "
            "(its only effect is an additional human-mode-only print section)",
        )
    finally:
        shutil.rmtree(g0_root, ignore_errors=True)

    print("  G21: two aliases resolving to one canonical root (shadow alias) -> both unavailable")
    g21_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g21-"))
    try:
        project = _pr3_project(g21_root)
        wiki = _pr3_wiki_root(g21_root)
        base_decl = _pr3_standard_declaration(wiki)
        two_alias_decl = {
            "version": 1,
            "roots": [
                base_decl["roots"][0],
                {**base_decl["roots"][0], "alias": "wiki2", "approved_by": "someone-else"},
            ],
        }
        _pr3_declare(project, two_alias_decl)

        # Control: two aliases at genuinely different roots stay available --
        # G21 must key on collision, not on "more than one alias declared".
        other = g21_root / "other-wiki"
        (other / "kernel").mkdir(parents=True, exist_ok=True)
        (other / "SCHEMA.md").write_text("# other\n", encoding="utf-8")
        (other / "kernel" / "facts.md").write_text("# facts\n", encoding="utf-8")
        _pr3_bind(
            project,
            {"version": 1, "bindings": {"wiki": {"path": str(wiki)}, "wiki2": {"path": str(other)}}},
        )
        roots, violations = verify_protocol.load_reference_roots(project)
        check(
            roots["wiki"].available
            and roots["wiki2"].available
            and not any(v["kind"] == "reference-root-shadow-alias" for v in violations),
            "G21 control: two aliases bound to two distinct roots are both available "
            "(the guard keys on canonical collision, not on alias count)",
        )

        def _g21_collision(label: str, second_path: str) -> None:
            _pr3_bind(
                project,
                {
                    "version": 1,
                    "bindings": {"wiki": {"path": str(wiki)}, "wiki2": {"path": second_path}},
                },
            )
            roots, violations = verify_protocol.load_reference_roots(project)
            shadow = [v for v in violations if v["kind"] == "reference-root-shadow-alias"]
            check(
                roots["wiki"].unavailable_reason == "shadow-alias"
                and roots["wiki2"].unavailable_reason == "shadow-alias"
                and roots["wiki"].canonical is None
                and roots["wiki2"].canonical is None
                and len(shadow) == 1,
                f"G21 ({label}): every alias in a colliding group is unavailable, with exactly "
                "one violation for the group -- not one survivor decided by declaration order",
            )
            # `all(...)` over a possibly-empty list, not `shadow[0]`: when the
            # guard is broken this sub-check must report a clean FAIL like the
            # one above, not raise IndexError and abort every later check.
            check(
                bool(shadow)
                and all(
                    str(wiki) not in v["detail"] and str(g21_root) not in v["detail"]
                    for v in shadow
                ),
                f"G21 ({label}) + G20: the shadow-alias detail names aliases only, never the "
                "shared directory's host path",
            )

        _g21_collision("identical declared string", str(wiki))
        _g21_collision("trailing slash", str(wiki) + "/")
        _g21_collision("dot segment", str(wiki) + "/./")
        _g21_collision("parent-then-back", str(wiki / "kernel" / ".." ))
        if hasattr(os, "symlink"):
            link = g21_root / "wiki-link"
            if not link.exists():
                link.symlink_to(wiki, target_is_directory=True)
            _g21_collision("symlink to the same tree", str(link))
            check(
                str(link) != str(wiki),
                "G21 mutation control: the two declared strings are literally different -- only "
                "canonical resolution exposes the collision; a string comparison would miss it",
            )
        else:
            print("  (skipped: os.symlink unavailable on this platform)")

        # End-to-end: a shadowed alias must not silently keep resolving citations.
        _pr3_bind(
            project,
            {"version": 1, "bindings": {"wiki": {"path": str(wiki)}, "wiki2": {"path": str(wiki)}}},
        )
        _pr3_write_review(project, "See `@@wiki/kernel/facts.md` for the fact.\n")
        result = subprocess.run(
            [sys.executable, str(LOOP_SCRIPTS / "verify_protocol.py"), "--project", str(project), "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        parsed = json.loads(result.stdout)
        kinds = [v["kind"] for v in parsed["violations"]]
        check(
            result.returncode != 0
            and "reference-root-shadow-alias" in kinds
            and "external-citation-unverifiable" in kinds
            and parsed["coverage"]["external_citations_resolved"] == 0,
            "G21 end-to-end: a citation through a shadowed alias resolves nothing and the gate "
            "fails -- shadowing is fail-closed, not a silently-tolerated duplicate declaration",
        )
    finally:
        shutil.rmtree(g21_root, ignore_errors=True)

    print("  G22: T-069 round-2 findings (same-directory identity, declaration integrity, honest coverage)")
    g22_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g22-"))
    try:
        # 22a: same directory reached under two spellings that `Path.resolve()`
        # does NOT fold together. On a case-insensitive volume that is the
        # wrong-case spelling; everywhere it is a hard link is not applicable
        # to directories, so the portable stand-in is a symlink, which G21
        # already covers. This check therefore *self-verifies its own premise*
        # first and skips honestly rather than passing vacuously.
        project = _pr3_project(g22_root)
        wiki = _pr3_wiki_root(g22_root / "case")
        alt = wiki.parent / wiki.name.swapcase()
        fixture_class = _case_fixture_class(wiki, alt)
        if fixture_class == "usable":
            check(
                alt.resolve() != wiki.resolve(),
                "G22a premise: on this volume the two spellings resolve to unequal canonical "
                "strings -- so grouping by Path equality genuinely could not see the collision",
            )
            check(
                os.path.samefile(alt, wiki),
                "G22a premise: ...while samefile() sees one directory (st_dev, st_ino)",
            )
            base = _pr3_standard_declaration(wiki)
            _pr3_declare(
                project,
                {
                    "version": 1,
                    "roots": [
                        base["roots"][0],
                        {**base["roots"][0], "alias": "wiki2", "approved_by": "someone-else"},
                    ],
                },
            )
            _pr3_bind(
                project,
                {
                    "version": 1,
                    "bindings": {"wiki": {"path": str(wiki)}, "wiki2": {"path": str(alt)}},
                },
            )
            roots, violations = verify_protocol.load_reference_roots(project)
            check(
                roots["wiki"].unavailable_reason == "shadow-alias"
                and roots["wiki2"].unavailable_reason == "shadow-alias"
                and len([v for v in violations if v["kind"] == "reference-root-shadow-alias"]) == 1,
                "G22a: two aliases naming one directory under different case are caught -- "
                "identity is samefile(), not canonical-string equality (T-069 F1.1)",
            )
        elif fixture_class == "resolve-folds":
            print(
                "  (skipped G22a: this volume is case-insensitive, but Path.resolve() already "
                "folds the two spellings to the same canonical string, so the premise this "
                "fixture needs -- 'grouping by Path equality could not see the collision' -- is "
                "false here, not reproducible. Coverage is not lost: G24a: _same_dir sees one "
                "directory through two unequal spellings -- this is the predicate G22a exercises "
                "via case, tested here without needing a case-insensitive volume)"
            )
        else:
            print("  (skipped G22a: this volume is case-sensitive; premise not reproducible here)")

        # 22b: the declaration artifacts must be the tracked files themselves.
        for label, rel, kind in (
            ("versioned", ".harnessloop/setup/reference-roots.json", "reference-roots-invalid"),
            (
                "local",
                ".harnessloop/local/reference-roots.local.json",
                "reference-root-local-invalid",
            ),
        ):
            b_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g22b-"))
            try:
                proj = _pr3_project(b_root)
                w = _pr3_wiki_root(b_root)
                _pr3_declare(proj, _pr3_standard_declaration(w))
                _pr3_bind(proj, {"version": 1, "bindings": {"wiki": {"path": str(w)}}})
                target = proj / rel
                outside = b_root / f"outside-{label}.json"
                outside.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
                target.unlink()
                if not hasattr(os, "symlink"):
                    print("  (skipped G22b: os.symlink unavailable)")
                    break
                target.symlink_to(outside)
                roots, violations = verify_protocol.load_reference_roots(proj)
                check(
                    roots == {} and any(v["kind"] == kind for v in violations),
                    f"G22b ({label}): a symlinked declaration loads zero roots -- what git shows "
                    "a reviewer and what the gate reads can never be two different files (T-069 F4)",
                )
            finally:
                shutil.rmtree(b_root, ignore_errors=True)

        # 22c: coverage must not under-report a declaration just because no
        # round exists yet -- that is the gate lying about this project's reach.
        c_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g22c-"))
        try:
            proj = _pr3_project(c_root)
            w = _pr3_wiki_root(c_root)
            _pr3_declare(proj, _pr3_standard_declaration(w))
            _pr3_bind(proj, {"version": 1, "bindings": {"wiki": {"path": str(w)}}})
            shutil.rmtree(proj / ".harnessloop" / "goals")
            result = subprocess.run(
                [
                    sys.executable,
                    str(LOOP_SCRIPTS / "verify_protocol.py"),
                    "--project",
                    str(proj),
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            cov = json.loads(result.stdout)["coverage"]
            check(
                cov["external_roots_declared"] == 1 and cov["external_roots_available"] == 1,
                "G22c: a project with a declaration but no rounds reports declared=1/available=1, "
                "not 0/0 -- a declaration is a project-level fact, not a per-round one (T-069 F4)",
            )
        finally:
            shutil.rmtree(c_root, ignore_errors=True)

        # 22d: `subpaths: []` is rejected outright rather than truthiness-collapsed
        # into "unrestricted" -- it reads as deny-all to a human.
        d_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g22d-"))
        try:
            proj = _pr3_project(d_root)
            w = _pr3_wiki_root(d_root)
            decl = _pr3_standard_declaration(w)
            decl["roots"][0]["subpaths"] = []
            _pr3_declare(proj, decl)
            _pr3_bind(proj, {"version": 1, "bindings": {"wiki": {"path": str(w)}}})
            roots, violations = verify_protocol.load_reference_roots(proj)
            check(
                roots == {} and any(v["kind"] == "reference-roots-invalid" for v in violations),
                "G22d: an explicit empty `subpaths` is invalid, never silently unrestricted "
                "(T-069 F4)",
            )
            decl["roots"][0]["subpaths"] = ["kernel"]
            _pr3_declare(proj, decl)
            roots, violations = verify_protocol.load_reference_roots(proj)
            check(
                roots.get("wiki") is not None and roots["wiki"].available,
                "G22d control: a non-empty subpaths list still loads -- the rejection is of the "
                "empty spelling, not of the key",
            )
        finally:
            shutil.rmtree(d_root, ignore_errors=True)

        # 22e: a wrong-typed `bound_at` is a schema error, not silently ignored.
        e_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g22e-"))
        try:
            proj = _pr3_project(e_root)
            w = _pr3_wiki_root(e_root)
            _pr3_declare(proj, _pr3_standard_declaration(w))
            _pr3_bind(
                proj,
                {"version": 1, "bindings": {"wiki": {"path": str(w), "bound_at": {"wrong": "type"}}}},
            )
            roots, violations = verify_protocol.load_reference_roots(proj)
            check(
                any(v["kind"] == "reference-root-local-invalid" for v in violations)
                and not roots["wiki"].available,
                "G22e: a non-string `bound_at` is rejected -- provenance is schema, not decoration "
                "(T-069 F4)",
            )
        finally:
            shutil.rmtree(e_root, ignore_errors=True)

        # 22f: zero-migration is byte-for-byte for a project with NO declaration
        # at all -- including the violation `detail`, not just the `kind`.
        f_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g22f-"))
        try:
            proj = _pr3_project(f_root)
            _pr3_write_review(proj, "See `@@foo/bar.md` and `nope/missing.md`.\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(LOOP_SCRIPTS / "verify_protocol.py"),
                    "--project",
                    str(proj),
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            details = [
                v["detail"] for v in json.loads(result.stdout)["violations"] if "@@foo" in v["detail"]
            ]
            check(
                len(details) == 1 and "is not a declared reference-root alias" not in details[0],
                "G22f: a project that declares no reference roots gets no alias hint appended to "
                "its dangling-citation detail -- zero-migration is byte-for-byte, not kind-only "
                "(T-069 F3)",
            )
        finally:
            shutil.rmtree(f_root, ignore_errors=True)

        # 22g: the hint DOES appear once the project declares roots -- 22f must
        # be the absence of a hint in the no-declaration case, not the hint
        # having been deleted outright.
        g_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g22g-"))
        try:
            proj = _pr3_project(g_root)
            w = _pr3_wiki_root(g_root)
            _pr3_declare(proj, _pr3_standard_declaration(w))
            _pr3_bind(proj, {"version": 1, "bindings": {"wiki": {"path": str(w)}}})
            _pr3_write_review(proj, "See `@@foo/bar.md`.\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(LOOP_SCRIPTS / "verify_protocol.py"),
                    "--project",
                    str(proj),
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            details = [
                v["detail"] for v in json.loads(result.stdout)["violations"] if "@@foo" in v["detail"]
            ]
            check(
                len(details) == 1
                and "is not a declared reference-root alias" in details[0]
                and "declared: wiki" in details[0],
                "G22g control: with roots declared, the undeclared-alias hint still appears and "
                "names the declared aliases -- 22f removed a migration artifact, not the feature",
            )
        finally:
            shutil.rmtree(g_root, ignore_errors=True)
    finally:
        shutil.rmtree(g22_root, ignore_errors=True)

    print("  G23: nesting is allowed but never silent (user ruling 2026-07-27; T-069 F1.2)")
    g23_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g23-"))
    try:
        project = _pr3_project(g23_root)
        wiki = _pr3_wiki_root(g23_root)
        (wiki / "kernel" / "deep").mkdir(parents=True, exist_ok=True)
        (wiki / "kernel" / "deep" / "x.md").write_text("# x\n", encoding="utf-8")
        base = _pr3_standard_declaration(wiki)["roots"][0]

        def _g23(label: str, roots_spec: list[dict], bind: dict[str, Path]):
            _pr3_declare(project, {"version": 1, "roots": roots_spec})
            _pr3_bind(
                project,
                {"version": 1, "bindings": {a: {"path": str(p)} for a, p in bind.items()}},
            )
            return verify_protocol.load_reference_roots(project)

        parent = {**base, "alias": "wiki", "expect_present": ["SCHEMA.md"]}
        child = {**base, "alias": "kern", "expect_present": ["facts.md"], "approved_by": "other"}
        grand = {**base, "alias": "dp", "expect_present": ["x.md"], "approved_by": "third"}
        bind3 = {"wiki": wiki, "kern": wiki / "kernel", "dp": wiki / "kernel" / "deep"}

        roots, violations = _g23("undeclared", [parent, child], {k: bind3[k] for k in ("wiki", "kern")})
        check(
            roots["wiki"].available
            and roots["kern"].unavailable_reason == "undeclared-nesting"
            and [v["kind"] for v in violations] == ["reference-root-undeclared-nesting"],
            "G23a: an undeclared nested root is fail-closed while its correctly-declared ancestor "
            "stays available -- the omission belongs to the descendant, not its neighbour",
        )
        roots, violations = _g23(
            "declared", [parent, {**child, "nested_under": "wiki"}], {k: bind3[k] for k in ("wiki", "kern")}
        )
        check(
            roots["wiki"].available and roots["kern"].available and violations == [],
            "G23b: once the nesting is declared in the versioned file, both roots are available "
            "and the gate is clean -- the ruling permits nesting, it only forbids hiding it",
        )
        roots, violations = _g23(
            "3-level",
            [parent, {**child, "nested_under": "wiki"}, {**grand, "nested_under": "kern"}],
            bind3,
        )
        check(
            all(roots[a].available for a in ("wiki", "kern", "dp")) and violations == [],
            "G23c: a 3-level chain where each root names its NEAREST declared ancestor is clean -- "
            "the a-c overlap is visible by transitivity, no list-valued key needed",
        )
        roots, violations = _g23(
            "skip-nearest",
            [parent, {**child, "nested_under": "wiki"}, {**grand, "nested_under": "wiki"}],
            bind3,
        )
        check(
            roots["dp"].unavailable_reason == "undeclared-nesting"
            and any(v["kind"] == "reference-root-undeclared-nesting" for v in violations),
            "G23d: naming a farther ancestor instead of the nearest one is still undeclared "
            "nesting -- otherwise the kern-dp overlap would stay invisible",
        )
        sibling = g23_root / "sibling"
        (sibling / "kernel").mkdir(parents=True, exist_ok=True)
        (sibling / "SCHEMA.md").write_text("# s\n", encoding="utf-8")
        roots, violations = _g23(
            "mismatch",
            [parent, {**child, "expect_present": ["SCHEMA.md"], "nested_under": "wiki"}],
            {"wiki": wiki, "kern": sibling},
        )
        check(
            roots["kern"].unavailable_reason == "nesting-mismatch"
            and any(v["kind"] == "reference-root-nesting-mismatch" for v in violations),
            "G23e: a root claiming nested_under a tree it does not actually sit inside on this "
            "machine is fail-closed -- the declaration must be true, not merely present",
        )
        for label, spec in (
            ("dangling target", [parent, {**child, "nested_under": "nope"}]),
            (
                "cycle",
                [
                    {**parent, "nested_under": "kern"},
                    {**child, "expect_present": ["SCHEMA.md"], "nested_under": "wiki"},
                ],
            ),
            ("self-reference", [parent, {**child, "nested_under": "kern"}]),
        ):
            roots, violations = _g23(label, spec, {k: bind3[k] for k in ("wiki", "kern")})
            check(
                roots == {} and any(v["kind"] == "reference-roots-invalid" for v in violations),
                f"G23f ({label}): a structurally broken nested_under is a whole-file schema error "
                "-- all-or-nothing, never a half-loaded declaration",
            )

        # The payoff of comparing by samefile rather than by string prefix.
        alt_parent = wiki.parent / wiki.name.swapcase()
        if alt_parent.exists() and str(alt_parent) != str(wiki):
            roots, violations = _g23(
                "case-variant ancestry",
                [parent, child],
                {"wiki": wiki, "kern": alt_parent / "kernel"},
            )
            check(
                roots["kern"].unavailable_reason == "undeclared-nesting",
                "G23g: ancestry is detected even when parent and child are spelled with different "
                "case -- a string-prefix test would see two unrelated trees and pass (T-069 F1.1 "
                "applied one layer up)",
            )
        else:
            print("  (skipped G23g: case-sensitive volume)")
    finally:
        shutil.rmtree(g23_root, ignore_errors=True)

    print("  G23h: G7 is emitted on both of verify_project's exits, not just the round-walking one")
    g23h_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g23h-"))
    try:
        proj = _pr3_project(g23h_root)
        _pr3_declare(proj, _pr3_standard_declaration(g23h_root / "wiki"))  # declared, never bound
        results = {}
        for label, keep_goals in (("with-goals", True), ("no-goals", False)):
            if not keep_goals:
                shutil.rmtree(proj / ".harnessloop" / "goals", ignore_errors=True)
            out = subprocess.run(
                [
                    sys.executable,
                    str(LOOP_SCRIPTS / "verify_protocol.py"),
                    "--project",
                    str(proj),
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            parsed = json.loads(out.stdout)
            results[label] = (
                out.returncode,
                sorted({v["kind"] for v in parsed["violations"]}),
                parsed["coverage"]["external_roots_declared"],
            )
        check(
            results["with-goals"] == results["no-goals"]
            and results["no-goals"][0] != 0
            and "external-root-unavailable" in results["no-goals"][1],
            "G23h: an unbound declared root fails the gate identically whether or not a goals/ "
            "directory exists -- exit code must not depend on a project having rounds yet "
            "(T-070 residual)",
        )
    finally:
        shutil.rmtree(g23h_root, ignore_errors=True)

    print("  G24: identity predicates, tested portably (the case fixtures above skip on a case-sensitive volume)")
    g24_root = Path(tempfile.mkdtemp(prefix="hl-pr3-g24-"))
    try:
        # G22a and G23g reproduce the real hole, but only on a case-insensitive
        # volume -- on case-sensitive CI they skip, leaving that hole unguarded
        # there (T-070 residual). These checks test the same two predicates
        # behaviorally on every platform, using a symlink to produce what a
        # wrong-case spelling produces: two unequal strings naming one
        # directory. They do not replace G22a/G23g (a symlink is not a
        # case-fold), they make the predicates' contract non-skippable.
        target = g24_root / "tree"
        (target / "kernel").mkdir(parents=True)
        if hasattr(os, "symlink"):
            link = g24_root / "tree-link"
            link.symlink_to(target, target_is_directory=True)
            check(
                str(link) != str(target) and Path(link) != Path(target),
                "G24 premise: the two spellings are unequal as strings and as Path objects",
            )
            check(
                verify_protocol._same_dir(link, target),
                "G24a: _same_dir sees one directory through two unequal spellings -- this is the "
                "predicate G22a exercises via case, tested here without needing a "
                "case-insensitive volume",
            )
            check(
                verify_protocol._is_strict_descendant(target / "kernel", link),
                "G24b: ancestry holds through an unequal spelling of the ancestor -- the predicate "
                "G23g exercises via case (a string-prefix test returns False here)",
            )
            check(
                not str(target / "kernel").startswith(str(link)),
                "G24b mutation control: a string-prefix implementation genuinely fails this "
                "input -- G24b is not passing for an unrelated reason",
            )
        else:
            print("  (skipped G24a/b: os.symlink unavailable)")
        check(
            verify_protocol._same_dir(g24_root / "gone-a", g24_root / "gone-b") is True,
            "G24c: an unanswerable comparison resolves as *same* -- fail-closed. 'We could not "
            "establish these are different directories' must never read as 'they are different' "
            "(T-070 residual)",
        )
        check(
            verify_protocol._same_dir(g24_root / "gone-a", g24_root / "gone-b", on_error=False)
            is False,
            "G24c control: the fail direction is a parameter, so G24c is asserting the callers' "
            "chosen direction rather than the only direction the function can return",
        )
        # Platform-independent backstop for the call sites themselves. Weaker
        # teeth than the fixtures above -- it asserts shape, so an equivalent
        # rewrite could trip it -- but it is the only layer that still runs on
        # a case-sensitive host, and its single job is to catch a refactor back
        # to canonical-string comparison.
        guard_src = inspect.getsource(verify_protocol.load_reference_roots)
        desc_src = inspect.getsource(verify_protocol._is_strict_descendant)
        check(
            "_same_dir(" in guard_src and "_same_dir(" in desc_src,
            "G24d (shape backstop): both the shadow-alias grouping and the ancestry walk go "
            "through _same_dir rather than comparing canonical paths directly",
        )
        check(
            "os.path.samefile" in inspect.getsource(verify_protocol._same_dir),
            "G24d (shape backstop): _same_dir is implemented on filesystem identity, not on "
            "string equality",
        )
    finally:
        shutil.rmtree(g24_root, ignore_errors=True)

    print("  G29: teeth for the windows-latest CI fix (stdout encoding + G22a's 3-way case classifier)")
    # G29a: the top-of-file stdout/stderr reconfigure must both (1) actually
    # be in effect right now, in this run, and (2) be defending against a
    # real crash rather than a hypothetical one. This file is allowed to
    # (and does) carry check() messages with non-ASCII text -- e.g. the
    # G25l message quoting '账本文件缺席 ⇒ 本规则零违规' verbatim -- and on
    # windows-latest (cp1252 default console codepage) printing that exact
    # message is what killed 5 straight CI runs. Pull the real offending
    # string out of this file's own source (not a hardcoded copy that could
    # silently drift out of sync) and prove it, encoded as cp1252, really
    # does raise UnicodeEncodeError -- without touching sys.stdout/stderr,
    # which stay reconfigured to UTF-8 throughout this process.
    _self_src = Path(__file__).read_text(encoding="utf-8")
    _crash_message_match = re.search(r'"([^"]*账本文件缺席[^"]*)"', _self_src)
    check(
        _crash_message_match is not None,
        "G29a premise: the check() message that crashed windows-latest CI ('账本文件缺席 ⇒ "
        "本规则零违规', see G25l above) still exists verbatim in this file -- the guard below "
        "tests the actual offending text, not a copy of it that could drift out of sync",
    )
    if _crash_message_match is not None:
        _would_crash = False
        try:
            _crash_message_match.group(1).encode("cp1252")
        except UnicodeEncodeError:
            _would_crash = True
        check(
            _would_crash,
            "G29a: that exact message genuinely raises UnicodeEncodeError when encoded as "
            "cp1252 (windows-latest's default console codepage, absent the reconfigure) -- "
            "proving this guard defends against a real crash, not a ceremonial one",
        )
    check(
        "utf8" in sys.stdout.encoding.lower().replace("-", ""),
        "G29a: sys.stdout.encoding is UTF-8 right now, in this process -- the top-of-file "
        "reconfigure is actually in effect, not merely present in source",
    )

    # G29b: _case_fixture_class's own branch selection, tested on every
    # platform (including this one) via fakes -- rather than trusting that
    # G22a's three real branches (case-sensitive / resolve-folds / usable)
    # get exercised just because three different CI runners exist. A fake
    # only needs to answer str()/.exists()/.resolve(), which is all
    # _case_fixture_class touches.
    class _FakeCasePath:
        def __init__(self, spelling: str, exists: bool, resolved: str):
            self._spelling = spelling
            self._exists = exists
            self._resolved = resolved

        def __str__(self) -> str:
            return self._spelling

        def exists(self) -> bool:
            return self._exists

        def resolve(self) -> "_FakeCasePath":
            return _FakeCasePath(self._resolved, True, self._resolved)

        def __eq__(self, other: object) -> bool:
            return isinstance(other, _FakeCasePath) and self._spelling == other._spelling

        def __hash__(self) -> int:
            return hash(self._spelling)

    _fake_wiki = _FakeCasePath("/fake/Wiki", True, "/fake/Wiki")
    check(
        _case_fixture_class(_fake_wiki, _FakeCasePath("/fake/wiki", False, "/fake/wiki"))
        == "case-sensitive",
        "G29b: a case-swapped spelling that does not exist at all classifies as "
        "case-sensitive (matches ubuntu-latest/ext4) -- the collision fixture is not "
        "reproducible, so G22a must skip rather than assert on it",
    )
    check(
        _case_fixture_class(_fake_wiki, _FakeCasePath("/fake/WIKI", True, "/fake/Wiki"))
        == "resolve-folds",
        "G29b: a case-swapped spelling that exists AND resolves identically to the original "
        "classifies as resolve-folds (matches windows-latest) -- G22a's own premise would be "
        "false here, so it must skip honestly instead of asserting something untrue, and G24a "
        "covers the predicate instead",
    )
    check(
        _case_fixture_class(_fake_wiki, _FakeCasePath("/fake/WIKI", True, "/fake/WIKI"))
        == "usable",
        "G29b: a case-swapped spelling that exists AND resolves to a genuinely different "
        "string classifies as usable (matches macos-latest/APFS default) -- the full G22a "
        "fixture (premise + samefile + shadow-alias detection) runs for real",
    )

    print("  G30: symlink-then-`..` platform semantics (windows-latest T-064 MUST-FIX C teeth)")
    # G30a: _classify_dotdot_symlink_resolution's own branch selection, tested on
    # every platform (including this one) via fabricated resolved-path triples --
    # rather than trusting that both real branches ("canonical"/"lexical") get
    # exercised just because more than one CI runner exists. The function only
    # compares its three inputs with `==`, so plain `Path` objects stand in for
    # real, resolved filesystem paths without touching a filesystem at all.
    _g30_outside_target = Path("/fake/outside/probe.txt")
    _g30_inside_target = Path("/fake/inside/probe.txt")
    check(
        _classify_dotdot_symlink_resolution(_g30_outside_target, _g30_outside_target, _g30_inside_target)
        == "canonical",
        "G30a: a resolution landing on the outside target classifies as 'canonical' "
        "(matches macos-latest/ubuntu-latest) -- Path.resolve() followed the symlink "
        "before applying the trailing `..`",
    )
    check(
        _classify_dotdot_symlink_resolution(_g30_inside_target, _g30_outside_target, _g30_inside_target)
        == "lexical",
        "G30a: a resolution landing on the inside target classifies as 'lexical' "
        "(matches windows-latest) -- `..` was erased before the symlink was ever "
        "consulted",
    )
    check(
        _classify_dotdot_symlink_resolution(
            Path("/fake/neither/probe.txt"), _g30_outside_target, _g30_inside_target
        )
        == "unrecognized",
        "G30a: a resolution matching NEITHER known target classifies as 'unrecognized' "
        "rather than silently defaulting to one of the two known semantics -- callers "
        "must fail loudly on this, not guess",
    )

    # G30b: the genuinely cross-platform half of T-064 MUST-FIX C's protection --
    # a project-internal symlink cited with NO `..` at all (`link/escape.md`) has
    # nothing for lexical `..` processing to erase, so it must be rejected under
    # BOTH semantics `_dotdot_symlink_semantics` can classify. Deliberately a
    # minimal, self-contained fixture (no git dependency, unlike the T-063
    # `symlink_containment_escape` fixture above whose equivalent assertion is
    # gated behind `git_available`) so this specific assertion is truly
    # unconditional on every platform where `os.symlink` works at all -- a live
    # check, never a skip.
    if hasattr(os, "symlink"):
        g30_root = REPO_ROOT / ".tmp" / f"verify-fixture-g30-pure-symlink-{uuid.uuid4().hex}"
        g30_project = g30_root / "project"
        g30_outside = g30_root / "outside"
        try:
            g30_project.mkdir(parents=True)
            g30_outside.mkdir(parents=True)
            try:
                (g30_project / "link").symlink_to(g30_outside, target_is_directory=True)
                g30_supported = True
            except (OSError, NotImplementedError):
                g30_supported = False
            if g30_supported:
                check(
                    verify_protocol._resolve_in_project(g30_project, "link/escape.md", g30_project)
                    is None,
                    "G30b: a pure symlink escape with NO `..` at all (`link/escape.md`, `link` "
                    "a project-internal symlink pointing outside the project) is rejected by "
                    "_resolve_in_project on the CURRENT platform -- unlike the `..`-cancellation "
                    "shape T-064 MUST-FIX C tests above, this vector has nothing for lexical `..` "
                    "processing to erase, so it must hold under both the 'canonical' and "
                    "'lexical' semantics _dotdot_symlink_semantics classifies -- a live, "
                    "unconditional assertion, proving the project boundary itself (not merely "
                    "this one `..` shape) is still enforced on every platform (T-063 MUST-FIX 2: "
                    "symlink_containment_escape)",
                )
            else:
                print("  (skipped G30b: symlinks unsupported on this filesystem)")
        finally:
            shutil.rmtree(g30_root, ignore_errors=True)
    else:
        print("  (skipped G30b: os.symlink unavailable on this platform)")

    print("  G19-strengthened: no escape knob, by shape rather than by three literal flag names")
    src = (LOOP_SCRIPTS / "verify_protocol.py").read_text(encoding="utf-8")
    parser_args = set(re.findall(r"add_argument\(\s*[\"'](--[a-z0-9-]+)[\"']", src))
    check(
        parser_args == {"--project", "--json", "--show-root-paths"},
        "G19: verify_protocol.py declares exactly --project/--json/--show-root-paths -- any new "
        "flag at all must be reviewed as a potential escape knob, not just the three names "
        "an earlier grep happened to look for (T-069 F5)",
    )
    check(
        not re.search(r"os\.environ(?:\.get)?\s*[\[(]\s*[\"']HARNESSLOOP", src),
        "G19: no HARNESSLOOP_* environment variable is read -- an env knob is an escape knob "
        "that no flag-name grep would ever see (T-069 F5)",
    )

    # -------------------------------------------------------------------
    # G25: RAE (round-acceptance-eval) gate -- `<goal>/evals.json`,
    # `<round>/evidence/runtime/acceptance-evals.json`, and the hard rule
    # tying a round's own ledger to that same round's own decision.md
    # Feedback (`verify_protocol.check_goal_eval_registry`,
    # `check_round_eval_ledger`, and the `acceptance-eval-*` violations
    # wired into `verify_round`). Every teeth below is a paired mutation:
    # a fixture asserted to land on verdict X under the real implementation,
    # then a specific, minimal change to that same fixture asserted to flip
    # the verdict -- proving the check discriminates on the exact condition
    # it claims to, not on some coincidental fixture property.
    # -------------------------------------------------------------------

    def _rae_project(tmp_root: Path) -> Path:
        """A minimal RAE-gate project fixture: one round ('0001') with
        `evidence/runtime/` ready and a parseable scope-lock.md (mirrors
        `_pr3_project`)."""
        project = tmp_root / "project"
        round_dir = project / ".harnessloop" / "goals" / "20260101-001-rae" / "rounds" / "0001"
        (round_dir / "evidence" / "runtime").mkdir(parents=True)
        (round_dir / "reviews").mkdir(parents=True)
        (round_dir / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            "- Write evidence under `rounds/0001/evidence/`.\n",
            encoding="utf-8",
        )
        return project

    def _rae_round_dir(project: Path) -> Path:
        return project / ".harnessloop" / "goals" / "20260101-001-rae" / "rounds" / "0001"

    def _rae_goal_dir(project: Path) -> Path:
        return project / ".harnessloop" / "goals" / "20260101-001-rae"

    def _rae_ledger_path(project: Path) -> Path:
        return _rae_round_dir(project) / "evidence" / "runtime" / "acceptance-evals.json"

    def _rae_write_ledger(project: Path, obj) -> None:
        text = obj if isinstance(obj, str) else json.dumps(obj)
        _rae_ledger_path(project).write_text(text, encoding="utf-8")

    def _rae_write_decision(project: Path, text: str) -> None:
        (_rae_round_dir(project) / "decision.md").write_text(text, encoding="utf-8")

    def _rae_write_registry(project: Path, obj) -> None:
        text = obj if isinstance(obj, str) else json.dumps(obj)
        (_rae_goal_dir(project) / "evals.json").write_text(text, encoding="utf-8")

    print("  G25a/b: due-set eval outcome determines whether Feedback: positive survives (pass vs fail)")
    g25_root = Path(tempfile.mkdtemp(prefix="hl-rae-g25-"))
    try:
        project = _rae_project(g25_root)
        _rae_write_decision(project, "# Decision\n\n- Feedback: positive\n")

        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "fail", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" in kinds,
            "G25a: due eval_id RAE-0001 has only a failing attempt, Feedback: positive -> "
            "acceptance-eval-positive-without-pass (red)",
        )

        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "pass", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" not in kinds,
            "G25b: flipping ONLY that entry's outcome to pass (same eval_id, same due set, same "
            "Feedback: positive) turns it green -- mutation control proving G25a is not a "
            "vacuous always-red",
        )

        print("  G25c: due eval_id entirely absent from entries (not even a failing attempt) + positive -> red")
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-9999", "attempt_id": "0001-a1", "outcome": "pass", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" in kinds,
            "G25c: the ledger has a passing entry for a DIFFERENT eval_id (RAE-9999), but "
            "nothing at all for the due id RAE-0001 -> red",
        )
        _rae_write_ledger(
            project,
            {
                "entries": [
                    {"eval_id": "RAE-9999", "attempt_id": "0001-a1", "outcome": "pass", "frozen_due_set": ["RAE-0001"]},
                    {"eval_id": "RAE-0001", "attempt_id": "0001-a2", "outcome": "pass", "frozen_due_set": ["RAE-0001"]},
                ]
            },
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" not in kinds,
            "G25c mutation control: adding the missing due id's OWN passing entry (leaving the "
            "unrelated RAE-9999 entry in place) turns it green -- proves the rule requires a "
            "pass keyed on that specific eval_id, not merely the presence of some pass "
            "somewhere in the ledger",
        )

        print("  G25d: attempt_id's leading 4 digits must equal the round directory name")
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0002-a1", "outcome": "pass", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-attempt-id-round-mismatch" in kinds,
            "G25d: attempt_id `0002-a1` inside round directory `0001` -> "
            "eval-ledger-attempt-id-round-mismatch (red)",
        )
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "pass", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-attempt-id-round-mismatch" not in kinds,
            "G25d mutation control: correcting the prefix to `0001` (matching the round "
            "directory) clears the violation",
        )

        print("  G25e: frozen_due_set is ALWAYS required, even as [] -- only the key's absence is a violation")
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "pass"}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-frozen-due-set-missing" in kinds,
            "G25e: an entry with no `frozen_due_set` key at all -> eval-ledger-frozen-due-set-missing (red)",
        )
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "pass", "frozen_due_set": []}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-frozen-due-set-missing" not in kinds,
            "G25e mutation control: an explicit empty list `[]` satisfies 'always required' -- "
            "only the KEY's absence is flagged, never an empty VALUE",
        )

        print("  G25f: two entries disagreeing on frozen_due_set is inconsistent; order alone is not")
        _rae_write_ledger(
            project,
            {
                "entries": [
                    {"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "pass", "frozen_due_set": ["RAE-0001"]},
                    {
                        "eval_id": "RAE-0002",
                        "attempt_id": "0001-a2",
                        "outcome": "pass",
                        "frozen_due_set": ["RAE-0001", "RAE-0002"],
                    },
                ]
            },
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-frozen-due-set-inconsistent" in kinds,
            "G25f: entry 1's frozen_due_set (`[RAE-0001]`) disagrees with entry 2's "
            "(`[RAE-0001, RAE-0002]`) -> eval-ledger-frozen-due-set-inconsistent (red)",
        )
        _rae_write_ledger(
            project,
            {
                "entries": [
                    {
                        "eval_id": "RAE-0001",
                        "attempt_id": "0001-a1",
                        "outcome": "pass",
                        "frozen_due_set": ["RAE-0001", "RAE-0002"],
                    },
                    {
                        "eval_id": "RAE-0002",
                        "attempt_id": "0001-a2",
                        "outcome": "pass",
                        "frozen_due_set": ["RAE-0001", "RAE-0002"],
                    },
                ]
            },
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-frozen-due-set-inconsistent" not in kinds,
            "G25f mutation control: aligning both entries' frozen_due_set removes the violation",
        )
        _rae_write_ledger(
            project,
            {
                "entries": [
                    {
                        "eval_id": "RAE-0001",
                        "attempt_id": "0001-a1",
                        "outcome": "pass",
                        "frozen_due_set": ["RAE-0001", "RAE-0002"],
                    },
                    {
                        "eval_id": "RAE-0002",
                        "attempt_id": "0001-a2",
                        "outcome": "pass",
                        "frozen_due_set": ["RAE-0002", "RAE-0001"],
                    },
                ]
            },
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-frozen-due-set-inconsistent" not in kinds,
            "G25f (order-insensitive): the same two eval_ids in a different order are the same "
            "due SET, not flagged as inconsistent",
        )

        print("  G25g: acceptance-evals.json is not legal JSON -> red, never a silent zero-violation return")
        naive_broken_loader_calls = []

        def _naive_broken_loader(path: Path) -> list:
            # The exact anti-pattern X1 forbids ("except: return []"), kept
            # here only to prove the contrast -- never called by production
            # code.
            try:
                json.loads(path.read_text(encoding="utf-8"))
                return []
            except Exception:
                return []

        _rae_ledger_path(project).write_text("{not valid json", encoding="utf-8")
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-invalid" in kinds,
            "G25g: malformed JSON ledger -> eval-ledger-invalid (red), not silently zero violations (X1)",
        )
        naive_broken_loader_calls.append(_naive_broken_loader(_rae_ledger_path(project)))
        check(
            naive_broken_loader_calls[0] == [],
            "G25g destructive control: a naive `except Exception: return []` loader (the exact "
            "anti-pattern X1 forbids) silently reports ZERO violations for this SAME malformed "
            "file -- check_round_eval_ledger does not take that shortcut, which is the entire "
            "reason this fixture is red instead of a silent pass",
        )

        print("  G25h: outcome must be exactly one of pass/fail/error/skipped -- no case-folding, no near-misses")
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "PASS", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-invalid-outcome" in kinds,
            "G25h: outcome `PASS` (wrong case) is not literally in {pass,fail,error,skipped} -> red",
        )
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "pass", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-invalid-outcome" not in kinds,
            "G25h mutation control: lowercase `pass` is accepted",
        )

        print("  G25i: evals.json top-level unknown key invalidates the WHOLE file")
        _rae_write_registry(
            project,
            {"evals": [{"eval_id": "RAE-0001", "activation_round": 1}], "extra_key": True},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "rae-invalid" in kinds,
            "G25i: evals.json declares an unknown top-level key (`extra_key`) alongside `evals` "
            "-> rae-invalid (whole file invalidated, red)",
        )
        _rae_write_registry(project, {"evals": [{"eval_id": "RAE-0001", "activation_round": 1}]})
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "rae-invalid" not in kinds,
            "G25i mutation control: removing the unknown key clears the violation",
        )

        print("  G25j: eval_id must be unique within evals.json")
        _rae_write_registry(
            project,
            {
                "evals": [
                    {"eval_id": "RAE-0001", "activation_round": 1},
                    {"eval_id": "RAE-0001", "activation_round": 2},
                ]
            },
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "rae-duplicate-eval-id" in kinds,
            "G25j: eval_id `RAE-0001` declared twice in evals.json -> rae-duplicate-eval-id (red)",
        )
        _rae_write_registry(
            project,
            {
                "evals": [
                    {"eval_id": "RAE-0001", "activation_round": 1},
                    {"eval_id": "RAE-0002", "activation_round": 2},
                ]
            },
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "rae-duplicate-eval-id" not in kinds,
            "G25j mutation control: giving the second entry a distinct eval_id clears the violation",
        )

        print("  G25 extra: activation_round must be int >= 1, and bool is explicitly excluded")
        _rae_write_registry(project, {"evals": [{"eval_id": "RAE-0001", "activation_round": True}]})
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "rae-invalid-activation-round" in kinds,
            "G25 extra: activation_round: true (a bool) is rejected even though "
            "isinstance(True, int) is True in Python -- red",
        )
        _rae_write_registry(project, {"evals": [{"eval_id": "RAE-0001", "activation_round": 1}]})
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "rae-invalid-activation-round" not in kinds,
            "G25 extra mutation control: activation_round: 1 (a genuine int >= 1) is accepted",
        )

        print("  G25k: Feedback: negative with an unsatisfied due id does NOT fire the positive-only rule")
        _rae_write_decision(project, "# Decision\n\n- Feedback: negative\n")
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "fail", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" not in kinds,
            "G25k: Feedback: negative with the SAME unsatisfied due eval_id -> the rule stays "
            "silent (it only constrains positive)",
        )
        _rae_write_decision(project, "# Decision\n\n- Feedback: positive\n")
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" in kinds,
            "G25k mutation control: flipping ONLY Feedback back to positive (identical ledger) "
            "now fires the rule -- proves G25k's greenness was really about Feedback, not a "
            "coincidence of ledger state",
        )
    finally:
        shutil.rmtree(g25_root, ignore_errors=True)

    print("  G25l: ledger file absent entirely -> zero violations from the RAE hard rule (OUT-list upper bound)")
    g25l_root = Path(tempfile.mkdtemp(prefix="hl-rae-g25l-"))
    try:
        project = _rae_project(g25l_root)
        _rae_write_decision(project, "# Decision\n\n- Feedback: positive\n")
        # Deliberately no acceptance-evals.json written at all.
        violations, coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" not in kinds
            and not any(k.startswith("eval-ledger-") for k in kinds)
            and coverage["rounds_eval_ledger_present"] == 0,
            "G25l: a round with `Feedback: positive` and NO acceptance-evals.json at all "
            "produces zero violations from the RAE gate -- the OUT-list upper bound "
            "'账本文件缺席 ⇒ 本规则零违规', pinned as an executable assertion",
        )
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "fail", "frozen_due_set": ["RAE-0001"]}]},
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" in kinds,
            "G25l mutation control: writing a ledger with an unsatisfied due id under the SAME "
            "decision.md immediately turns it red -- proves G25l's greenness was specifically "
            "about file absence, not a coincidental fixture blind spot",
        )
    finally:
        shutil.rmtree(g25l_root, ignore_errors=True)

    print("  G25m: acceptance-evals.json with a duplicate key -> red, proving object_pairs_hook is really wired")
    g25m_root = Path(tempfile.mkdtemp(prefix="hl-rae-g25m-"))
    try:
        project = _rae_project(g25m_root)
        _rae_write_decision(project, "# Decision\n\n- Feedback: positive\n")
        dup_key_text = (
            '{"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", '
            '"outcome": "pass", "outcome": "fail", "frozen_due_set": ["RAE-0001"]}]}'
        )
        _rae_write_ledger(project, dup_key_text)
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "eval-ledger-invalid" in kinds,
            "G25m: acceptance-evals.json with a duplicate `outcome` key -> eval-ledger-invalid (red)",
        )
        naive = json.loads(dup_key_text)
        check(
            naive["entries"][0]["outcome"] == "fail",
            "G25m destructive control: plain json.loads (the stdlib default, no "
            "object_pairs_hook) silently accepts this EXACT duplicate-key document and keeps "
            "only the LAST 'outcome' value ('fail') without complaint -- if "
            "check_round_eval_ledger used plain json.loads instead of _load_strict_json, this "
            "fixture would have gone GREEN instead of red",
        )
    finally:
        shutil.rmtree(g25m_root, ignore_errors=True)

    print("  G25n: Feedback with full-width punctuation is fail-closed unparsable, never silently 'not positive'")
    g25n_root = Path(tempfile.mkdtemp(prefix="hl-rae-g25n-"))
    try:
        project = _rae_project(g25n_root)
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "fail", "frozen_due_set": ["RAE-0001"]}]},
        )
        _rae_write_decision(project, "# Decision\n\n- Feedback: positive。\n")  # trailing full-width period
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-feedback-unparsable" in kinds,
            "G25n: `Feedback: positive。` (trailing full-width period, U+3002) does not "
            "normalize to a known value -> acceptance-eval-feedback-unparsable (red)",
        )
        check(
            "acceptance-eval-positive-without-pass" not in kinds,
            "G25n: the positive-without-pass rule does not ALSO fire when Feedback could not "
            "be determined -- the two kinds are reported as distinct, non-overlapping facts",
        )
        naive_normalized = "positive。".strip().lower()
        check(
            naive_normalized not in verify_protocol.FEEDBACK_KNOWN_VALUES,
            "G25n destructive control: the raw value genuinely fails a plain known-set "
            "membership test after only strip/lower -- if _normalize_feedback's None were "
            "instead treated as 'not positive' (fail-open) rather than its own violation, this "
            "fixture would have silently produced zero violations from the RAE gate",
        )
        _rae_write_decision(project, "# Decision\n\n- Feedback: positive\n")
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-feedback-unparsable" not in kinds and "acceptance-eval-positive-without-pass" in kinds,
            "G25n mutation control: fixing the spelling to plain ASCII `positive` clears the "
            "unparsable violation and correctly promotes to positive-without-pass (same "
            "unsatisfied due id, now recognized instead of silently ignored)",
        )
    finally:
        shutil.rmtree(g25n_root, ignore_errors=True)

    # -------------------------------------------------------------------
    # G26: second RAE vertical slice -- decision.md's optional
    # `- Acceptance evals: ran` / `none — <reason>` field
    # (`verify_protocol.check_acceptance_eval_declaration`,
    # `parse_acceptance_eval_declaration`,
    # `_normalize_acceptance_eval_declaration`). This narrows the G25l upper
    # bound ("ledger absent -> zero violations from the RAE hard rule")
    # WITHOUT ever joining across time layers: both operands here -- the
    # decision.md text and this SAME round's own ledger presence -- come
    # from one round, exactly like B2a's `check_review_declaration`; neither
    # `<goal>/evals.json` nor `activation_round` is ever read by this gate.
    #
    # Eight letters below, one per row of the judgment table this vertical
    # slice's brief specifies. Every letter proves its primary claim AND its
    # opposite via an explicit fixture mutation -- never just one direction.
    # None of these fixtures ever write a `- Feedback:` line, so the
    # pre-existing `acceptance-eval-feedback-unparsable` /
    # `acceptance-eval-positive-without-pass` kinds (the FIRST RAE vertical
    # slice) never fire here; filtering violations by the shared
    # `acceptance-eval-` prefix therefore isolates exactly this gate's own
    # five kinds without needing to enumerate them by name at every call site.
    # -------------------------------------------------------------------

    def _accept_kinds(violations: list[dict]) -> set[str]:
        return {v["kind"] for v in violations if v["kind"].startswith("acceptance-eval-")}

    print("  G26a: field absent + ledger present -> acceptance-eval-declaration-missing (red)")
    g26_root = Path(tempfile.mkdtemp(prefix="hl-rae-g26a-"))
    try:
        project = _rae_project(g26_root)
        _rae_write_decision(project, "# Decision\n\n- Verdict: pass\n")
        _rae_write_ledger(project, {"entries": []})
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declaration-missing" in _accept_kinds(violations),
            "G26a: decision.md has no `- Acceptance evals:` line but this round's "
            "ledger exists -> acceptance-eval-declaration-missing (red) -- row 2 of "
            "the second RAE vertical slice's judgment table",
        )

        _rae_write_decision(project, "# Decision\n\n- Verdict: pass\n- Acceptance evals: ran\n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declaration-missing" not in _accept_kinds(violations),
            "G26a mutation control: declaring `Acceptance evals: ran` (same ledger, "
            "otherwise-unchanged decision.md) clears the violation -- proves it is "
            "really about the field's absence, not a coincidental fixture property",
        )
    finally:
        shutil.rmtree(g26_root, ignore_errors=True)

    print("  G26b: `Acceptance evals: ran` + ledger present -> green; deleting ONLY the ledger turns it red")
    g26_root = Path(tempfile.mkdtemp(prefix="hl-rae-g26b-"))
    try:
        project = _rae_project(g26_root)
        _rae_write_decision(project, "# Decision\n\n- Acceptance evals: ran\n")
        _rae_write_ledger(project, {"entries": []})
        violations, _coverage = verify_protocol.verify_project(project)
        accept_kinds = _accept_kinds(violations)
        check(
            not accept_kinds,
            f"G26b: `Acceptance evals: ran` with this round's ledger present -> no "
            f"acceptance-eval-* violation (row 3, got {sorted(accept_kinds)})",
        )

        _rae_ledger_path(project).unlink()
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declared-ran-without-ledger" in _accept_kinds(violations),
            "G26b mutation control: deleting ONLY the ledger file (same `Acceptance "
            "evals: ran` declaration) turns this round red -- proves G26b's greenness "
            "depended on the ledger's actual presence, not a vacuous always-green path",
        )
    finally:
        shutil.rmtree(g26_root, ignore_errors=True)

    print("  G26c: `Acceptance evals: none — <reason>` + ledger absent -> green; adding a ledger turns it red")
    g26_root = Path(tempfile.mkdtemp(prefix="hl-rae-g26c-"))
    try:
        project = _rae_project(g26_root)
        _rae_write_decision(
            project, "# Decision\n\n- Acceptance evals: none — smoke test only, no eval harness yet\n"
        )
        violations, _coverage = verify_protocol.verify_project(project)
        accept_kinds = _accept_kinds(violations)
        check(
            not accept_kinds,
            f"G26c: `Acceptance evals: none — <non-empty reason>` with no ledger for "
            f"this round -> no acceptance-eval-* violation (row 5, got {sorted(accept_kinds)})",
        )

        _rae_write_ledger(project, {"entries": []})
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declaration-contradicts-ledger" in _accept_kinds(violations),
            "G26c mutation control: adding ONLY a ledger (same `Acceptance evals: none "
            "— ...` declaration) turns this round red -- proves G26c's greenness "
            "depended on the ledger's actual absence, not a vacuous always-green path",
        )
    finally:
        shutil.rmtree(g26_root, ignore_errors=True)

    print("  G26d: `Acceptance evals: ran` + ledger absent -> acceptance-eval-declared-ran-without-ledger (red)")
    g26_root = Path(tempfile.mkdtemp(prefix="hl-rae-g26d-"))
    try:
        project = _rae_project(g26_root)
        _rae_write_decision(project, "# Decision\n\n- Acceptance evals: ran\n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declared-ran-without-ledger" in _accept_kinds(violations),
            "G26d: `Acceptance evals: ran` with NO acceptance-evals.json written for "
            "this round -> acceptance-eval-declared-ran-without-ledger (red) -- row 4",
        )

        _rae_write_ledger(project, {"entries": []})
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declared-ran-without-ledger" not in _accept_kinds(violations),
            "G26d mutation control: writing the ledger (same `Acceptance evals: ran` "
            "declaration) clears the violation",
        )
    finally:
        shutil.rmtree(g26_root, ignore_errors=True)

    print("  G26e: field absent + ledger absent -> zero violations (OUT-list upper bound: migration-silent)")
    g26_root = Path(tempfile.mkdtemp(prefix="hl-rae-g26e-"))
    try:
        project = _rae_project(g26_root)
        _rae_write_decision(project, "# Decision\n\n- Verdict: pass\n")
        # Deliberately no `- Acceptance evals:` line and no acceptance-evals.json --
        # this is the residual OUT-list upper bound harnessloop-loop/SKILL.md now
        # documents under "Narrowed, not closed, by the second vertical slice": a
        # round that writes NEITHER the field NOR the ledger produces zero
        # violations from this gate, forever -- the gate can only guarantee
        # self-consistency once declared, never that declaration happens.
        violations, _coverage = verify_protocol.verify_project(project)
        accept_kinds = _accept_kinds(violations)
        check(
            not accept_kinds,
            f"G26e: no `Acceptance evals:` declaration and no ledger for this round -> "
            f"zero acceptance-eval-* violations (migration-silent, row 1, got {sorted(accept_kinds)})",
        )

        # Reverse mutation (required by the brief): add ONLY a ledger to the SAME
        # round, decision.md unchanged -- this must turn the round red, proving
        # G26e's greenness was because the condition (ledger absent) was genuinely
        # not met, not because the check never runs at all.
        _rae_write_ledger(project, {"entries": []})
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declaration-missing" in _accept_kinds(violations),
            "G26e mutation control: adding ONLY a ledger to the SAME round (decision.md "
            "unchanged, still no `Acceptance evals:` line) immediately turns it red -- "
            "proves G26e's greenness was real, not a coincidental blind spot where the "
            "check simply never executes",
        )
    finally:
        shutil.rmtree(g26_root, ignore_errors=True)

    print(
        "  G26f: `Acceptance evals: none — <reason>` + ledger present -> "
        "acceptance-eval-declaration-contradicts-ledger (red)"
    )
    g26_root = Path(tempfile.mkdtemp(prefix="hl-rae-g26f-"))
    try:
        project = _rae_project(g26_root)
        _rae_write_decision(
            project, "# Decision\n\n- Acceptance evals: none — smoke test only, no eval harness yet\n"
        )
        _rae_write_ledger(project, {"entries": []})
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declaration-contradicts-ledger" in _accept_kinds(violations),
            "G26f: `Acceptance evals: none — <reason>` while this round's ledger "
            "exists -> acceptance-eval-declaration-contradicts-ledger (red) -- row 6",
        )

        _rae_ledger_path(project).unlink()
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-declaration-contradicts-ledger" not in _accept_kinds(violations),
            "G26f mutation control: deleting ONLY the ledger (same `Acceptance evals: "
            "none — ...` declaration) clears the violation",
        )
    finally:
        shutil.rmtree(g26_root, ignore_errors=True)

    print(
        "  G26g: `Acceptance evals: none —` with empty/whitespace reason -> "
        "acceptance-eval-none-reason-empty (red), regardless of ledger state"
    )
    g26_root = Path(tempfile.mkdtemp(prefix="hl-rae-g26g-"))
    try:
        project = _rae_project(g26_root)
        _rae_write_decision(project, "# Decision\n\n- Acceptance evals: none —   \n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-none-reason-empty" in _accept_kinds(violations),
            "G26g: `Acceptance evals: none —` with only whitespace after the "
            "separator, ledger absent -> acceptance-eval-none-reason-empty (red) -- row 7",
        )

        _rae_write_ledger(project, {"entries": []})
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "acceptance-eval-none-reason-empty" in _accept_kinds(violations),
            "G26g: the SAME empty-reason declaration still fires with a ledger "
            "present too -- row 7 is 'either' ledger state, not conditioned on it",
        )

        _rae_ledger_path(project).unlink()
        _rae_write_decision(
            project, "# Decision\n\n- Acceptance evals: none — smoke test only, no eval harness yet\n"
        )
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            not _accept_kinds(violations),
            "G26g mutation control: filling in a non-empty reason (and removing the "
            "ledger, back to row 5) clears acceptance-eval-none-reason-empty and "
            "produces zero acceptance-eval-* violations -- proves the check is really "
            "about the reason's emptiness, not a vacuous always-red path",
        )
    finally:
        shutil.rmtree(g26_root, ignore_errors=True)

    print(
        "  G26h: unparsable Acceptance evals value (full-width period) -> "
        "acceptance-eval-declaration-unparsable (red), fail-closed and alone"
    )
    g26_root = Path(tempfile.mkdtemp(prefix="hl-rae-g26h-"))
    try:
        project = _rae_project(g26_root)
        _rae_write_decision(project, "# Decision\n\n- Acceptance evals: ran。\n")  # trailing full-width period, U+3002
        _rae_write_ledger(project, {"entries": []})
        violations, _coverage = verify_protocol.verify_project(project)
        accept_kinds = _accept_kinds(violations)
        check(
            accept_kinds == {"acceptance-eval-declaration-unparsable"},
            "G26h: `Acceptance evals: ran。` (trailing full-width period) does not "
            "normalize to `ran` or `none — ...` -> acceptance-eval-declaration-unparsable "
            f"(red) -- row 8, and no OTHER acceptance-eval-* kind fires alongside it "
            f"(got {sorted(accept_kinds)}), proving fail-closed took its own independent "
            "branch rather than some other rule silently absorbing it",
        )
        naive_normalized = "ran。".strip().lower()
        check(
            naive_normalized != verify_protocol.ACCEPTANCE_EVAL_RAN_TOKEN,
            "G26h destructive control: the raw value genuinely fails a plain `== "
            '"ran"` membership test after only strip/lower -- if '
            "_normalize_acceptance_eval_declaration folded this to 'ran' anyway (e.g. "
            "by stripping trailing punctuation), or treated an unrecognized value as "
            "absent (fail-open), this fixture would have silently produced zero "
            "acceptance-eval-* violations",
        )

        _rae_write_decision(project, "# Decision\n\n- Acceptance evals: ran\n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            not _accept_kinds(violations),
            "G26h mutation control: fixing the spelling to plain ASCII `ran` (same "
            "ledger present) clears the unparsable violation and correctly resolves "
            "to green -- same fixture, only the punctuation differs",
        )
    finally:
        shutil.rmtree(g26_root, ignore_errors=True)

    # -------------------------------------------------------------------
    # G27: fenced code blocks must not leak into the `- <label>:` line-
    # prefix parsers (`parse_feedback`, `parse_review_fields`,
    # `parse_acceptance_eval_declaration`, all routed through the shared
    # `_uncoded_lines` filter). Live false green, reproduced: a decision.md
    # with a fenced-block example reading `- Feedback: negative` followed,
    # outside the fence, by the round's real `- Feedback: positive` was read
    # as `negative` by the pre-fix "first occurrence wins" scan -- silently
    # defeating `acceptance-eval-positive-without-pass` for a round whose
    # actual (rendered) claim was positive. Every letter below proves its
    # primary claim AND flips it via an explicit fixture mutation, per this
    # file's convention -- never just one direction.
    # -------------------------------------------------------------------

    print(
        "  G27a (flagship): fenced `- Feedback: negative` + real `- Feedback: positive` "
        "+ a failing due eval -> acceptance-eval-positive-without-pass (red), and the "
        "fence is genuinely load-bearing both ways"
    )
    g27_root = Path(tempfile.mkdtemp(prefix="hl-rae-g27a-"))
    try:
        project = _rae_project(g27_root)
        _rae_write_ledger(
            project,
            {"entries": [{"eval_id": "RAE-0001", "attempt_id": "0001-a1", "outcome": "fail", "frozen_due_set": ["RAE-0001"]}]},
        )

        fenced_text = (
            "# Decision\n\n"
            "```\n"
            "- Feedback: negative\n"
            "```\n"
            "- Feedback: positive\n"
            "- Review: none — n/a\n"
            "- Reviewer: me\n"
            "- Review verdict: pass\n"
        )
        _rae_write_decision(project, fenced_text)
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" in kinds,
            "G27a: decision.md's real (unfenced) Feedback is positive, the due "
            "RAE-0001 eval's only attempt is a fail, and a fenced-block example "
            "claiming `Feedback: negative` sits earlier in the file -> "
            f"acceptance-eval-positive-without-pass still fires (got {sorted(kinds)})",
        )

        # Reverse 1: delete the fenced example lines entirely (same real
        # Feedback: positive, same failing ledger). The violation must
        # survive identically -- proving G27a's redness is not somehow
        # propped up by the fenced content that happens to sit above it.
        unfenced_text = (
            "# Decision\n\n"
            "- Feedback: positive\n"
            "- Review: none — n/a\n"
            "- Reviewer: me\n"
            "- Review verdict: pass\n"
        )
        _rae_write_decision(project, unfenced_text)
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" in kinds,
            "G27a destructive control: removing the fenced ```/Feedback: "
            "negative/``` lines entirely (same real Feedback: positive, same "
            "failing ledger) still fires the rule -- proves the violation was "
            "never resting on the fenced content, only on the real, unfenced "
            "declaration",
        )

        # Reverse 2: flip the REAL (unfenced) Feedback to negative, leaving
        # the fenced block untouched. The violation must clear -- proving
        # the parser genuinely reads the unfenced line, not the fenced one.
        flipped_text = (
            "# Decision\n\n"
            "```\n"
            "- Feedback: negative\n"
            "```\n"
            "- Feedback: negative\n"
            "- Review: none — n/a\n"
            "- Reviewer: me\n"
            "- Review verdict: pass\n"
        )
        _rae_write_decision(project, flipped_text)
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "acceptance-eval-positive-without-pass" not in kinds,
            "G27a mutation control: changing ONLY the real, unfenced Feedback "
            "line to negative (the fenced example is untouched) clears the "
            "violation -- proves the parser is genuinely reading the unfenced "
            "line's value, not the fenced sham",
        )
    finally:
        shutil.rmtree(g27_root, ignore_errors=True)

    print("  G27b: `~~~` fences hide fenced content exactly like ``` fences do")
    g27b_fenced = "# Decision\n\n~~~\n- Feedback: negative\n~~~\n- Feedback: positive\n"
    check(
        verify_protocol.parse_feedback(g27b_fenced) == "positive",
        "G27b: a `~~~`-fenced `- Feedback: negative` does not shadow the real, "
        "unfenced `- Feedback: positive` below it (got "
        f"{verify_protocol.parse_feedback(g27b_fenced)!r})",
    )
    g27b_unfenced = g27b_fenced.replace("~~~\n", "")
    check(
        verify_protocol.parse_feedback(g27b_unfenced) == "negative",
        "G27b mutation control: removing ONLY the two `~~~` marker lines "
        "(same two Feedback lines, same order) flips the result back to "
        "'negative' via first-occurrence-wins -- proves the `~~~` markers "
        f"themselves were what hid the first line (got {verify_protocol.parse_feedback(g27b_unfenced)!r})",
    )

    print("  G27c: a shorter same-type run inside a longer fence does not close it")
    g27c_text = (
        "# Decision\n\n"
        "````\n"
        "- Feedback: negative\n"
        "```\n"
        "- Feedback: also-inside\n"
        "````\n"
        "- Feedback: positive\n"
    )
    check(
        verify_protocol.parse_feedback(g27c_text) == "positive",
        "G27c: a 4-backtick-opened fence containing a bare 3-backtick line is "
        "not closed by it -- both `negative` and `also-inside` stay fenced, "
        "and the real `- Feedback: positive` below the true (4-backtick) "
        f"close wins (got {verify_protocol.parse_feedback(g27c_text)!r})",
    )

    def _naive_fence_toggle_feedback(text: str) -> str | None:
        """Counterfactual only, never a real code path: a length-blind fence
        scanner that treats ANY run of 3+ backticks or tildes as toggling
        fence state, ignoring the opening run's length entirely. Used to
        show what G27c's fixture WOULD read if `_uncoded_lines` did not
        enforce `len(closing run) >= len(opening run)`.
        """
        in_fence = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if not in_fence and stripped.lower().startswith("- feedback:"):
                return stripped.split(":", 1)[1].strip()
        return None

    check(
        _naive_fence_toggle_feedback(g27c_text) == "also-inside",
        "G27c destructive control: a length-blind naive scanner (any run "
        "closes any fence) would let the bare 3-backtick line close the "
        "4-backtick fence early, exposing `- Feedback: also-inside` as the "
        "first unfenced Feedback line -- proving the real implementation's "
        "run-length comparison is what keeps it fenced, not mere accident "
        f"(naive got {_naive_fence_toggle_feedback(g27c_text)!r} vs. real "
        f"{verify_protocol.parse_feedback(g27c_text)!r})",
    )

    print("  G27d: a closing-looking fence line carrying an info string does not close the fence")
    g27d_text = (
        "# Decision\n\n"
        "```\n"
        "- Feedback: negative\n"
        "``` still-open\n"
        "- Feedback: positive\n"
    )
    check(
        verify_protocol.parse_feedback(g27d_text) is None,
        "G27d: '``` still-open' carries trailing text after the backtick "
        "run, so it does not close the fence -- the fence stays open "
        "through EOF (G27f's fail-closed rule), swallowing BOTH Feedback "
        f"lines, so parse_feedback returns None (got {verify_protocol.parse_feedback(g27d_text)!r})",
    )
    g27d_closed = g27d_text.replace("``` still-open\n", "```\n")
    check(
        verify_protocol.parse_feedback(g27d_closed) == "positive",
        "G27d mutation control: stripping ONLY the ' still-open' info string "
        "from that same line (leaving a bare ```) makes it a genuine close, "
        "exposing the real `- Feedback: positive` below -- proves the info "
        f"string was what disqualified it (got {verify_protocol.parse_feedback(g27d_closed)!r})",
    )

    print("  G27e: a 3-space-indented fence counts; a 4-space-indented one does not (pins the registered upper bound)")
    g27e_3space = "# Decision\n\n   ```\n- Feedback: negative\n   ```\n- Feedback: positive\n"
    check(
        verify_protocol.parse_feedback(g27e_3space) == "positive",
        "G27e: a fence indented by exactly 3 spaces is still recognized as a "
        f"fence (got {verify_protocol.parse_feedback(g27e_3space)!r})",
    )
    # This is NOT a missed case: it pins the documented upper bound (see
    # `_uncoded_lines`'s "known gap" paragraph and harnessloop-loop/SKILL.md's
    # OUT column) that a 4-space indent is CommonMark's *indented code block*
    # syntax, a different construct this fix deliberately does not track.
    g27e_4space = "# Decision\n\n    ```\n- Feedback: negative\n    ```\n- Feedback: positive\n"
    check(
        verify_protocol.parse_feedback(g27e_4space) == "negative",
        "G27e: a fence-shaped line indented by 4 spaces is NOT recognized as "
        "a fence (registered gap, not a silent miss) -- first-occurrence-wins "
        f"reads the 'negative' line as live prose (got {verify_protocol.parse_feedback(g27e_4space)!r})",
    )

    print("  G27f: an unclosed fence swallows every field after it through EOF -> review-declaration-missing (fail-closed)")
    g27f_root = Path(tempfile.mkdtemp(prefix="hl-rae-g27f-"))
    try:
        project = _rae_project(g27f_root)
        _rae_write_decision(
            project,
            "# Decision\n\n```\n- Review: none — n/a\n- Reviewer: me\n- Review verdict: pass\n",
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "review-declaration-missing" in kinds,
            "G27f: an opening fence with no closing marker before EOF makes "
            "every Review/Reviewer/Review verdict line after it fenced (and "
            "thus invisible) -- the three required fields are genuinely "
            f"absent -> review-declaration-missing (got {sorted(kinds)})",
        )

        _rae_write_decision(
            project,
            "# Decision\n\n```\n```\n- Review: none — n/a\n- Reviewer: me\n- Review verdict: pass\n",
        )
        violations, _coverage = verify_protocol.verify_project(project)
        kinds = {v["kind"] for v in violations}
        check(
            "review-declaration-missing" not in kinds,
            "G27f mutation control: inserting the missing closing ``` "
            "immediately (same three field lines, now genuinely outside the "
            "fence) clears review-declaration-missing -- proves it was "
            "genuinely the unclosed fence swallowing the fields, not "
            f"something else about the fixture (got {sorted(kinds)})",
        )
    finally:
        shutil.rmtree(g27f_root, ignore_errors=True)

    print(
        "  G27g: parse_review_fields and parse_acceptance_eval_declaration are EACH "
        "independently fence-guarded -- not only parse_feedback"
    )
    fenced_reviewer = "# Decision\n\n```\n- Reviewer: fenced-fake\n```\n"
    fields = verify_protocol.parse_review_fields(fenced_reviewer)
    check(
        fields["reviewer"] is None,
        "G27g: parse_review_fields ignores a `- Reviewer:` line that only "
        f"appears inside a fence -- the field is genuinely absent (got {fields})",
    )
    unfenced_reviewer = fenced_reviewer.replace("```\n", "")
    fields2 = verify_protocol.parse_review_fields(unfenced_reviewer)
    check(
        fields2["reviewer"] == "fenced-fake",
        "G27g mutation control: removing ONLY the fence markers around the "
        "same `- Reviewer:` line exposes it -- proves the fence itself was "
        f"hiding it, not some other property of the text (got {fields2})",
    )

    fenced_accept = "# Decision\n\n```\n- Acceptance evals: ran\n```\n"
    check(
        verify_protocol.parse_acceptance_eval_declaration(fenced_accept) is None,
        "G27g: parse_acceptance_eval_declaration ignores a `- Acceptance "
        "evals:` line that only appears inside a fence -- the field is "
        "genuinely absent (got "
        f"{verify_protocol.parse_acceptance_eval_declaration(fenced_accept)!r})",
    )
    unfenced_accept = fenced_accept.replace("```\n", "")
    check(
        verify_protocol.parse_acceptance_eval_declaration(unfenced_accept) == "ran",
        "G27g mutation control: removing ONLY the fence markers around the "
        "same `- Acceptance evals:` line exposes it -- proves the fence "
        "itself was hiding it (got "
        f"{verify_protocol.parse_acceptance_eval_declaration(unfenced_accept)!r})",
    )

    # G31: TH-0026 (evolution-issues/0026-scope-lock-nonexistent-path-silent-
    # zero-coverage.md) -- a scope-lock span naming this round's own number
    # but dropping the `goals/<slug>/` segment out of its path (e.g.
    # `.harnessloop/rounds/0008/` instead of the real
    # `.harnessloop/goals/<slug>/rounds/0008/`) authorizes a location Rule A
    # never finds a single file under -- silent zero coverage, exit 0.
    # G31a-e exercise `scope_lock_round_path_mismatch` directly: it is a pure
    # function over Path objects (round_dir.name / .parent.parent /
    # relative_to) with zero filesystem access, so a synthetic project/round
    # path that never touches disk is enough -- no tempdir needed. G31f/g
    # exercise the real `verify_project` integration (coverage + violations).
    print("  G31: TH-0026 scope-lock span names this round but the wrong path prefix -> hint, never a violation")
    th0026_project = Path("/th0026-synthetic/project")
    th0026_goal_slug = "20260718-002-agent-app"
    th0026_round_dir = th0026_project / ".harnessloop" / "goals" / th0026_goal_slug / "rounds" / "0008"

    print("  G31a: '.harnessloop/rounds/0008/' (real repo's actual rounds/0008 mistake) is flagged")
    note_a = verify_protocol.scope_lock_round_path_mismatch(
        ".harnessloop/rounds/0008/", th0026_round_dir, th0026_project
    )
    check(
        note_a is not None,
        f"G31a: '.harnessloop/rounds/0008/' (missing the goals/{th0026_goal_slug}/ segment) is "
        f"flagged as a round-path mismatch (got {note_a!r})",
    )
    note_a_real = verify_protocol.scope_lock_round_path_mismatch(
        f".harnessloop/goals/{th0026_goal_slug}/rounds/0008/", th0026_round_dir, th0026_project
    )
    check(
        note_a_real is None,
        "G31a mutation control: the round's real, full path "
        f"('.harnessloop/goals/{th0026_goal_slug}/rounds/0008/') is NOT flagged "
        f"(got {note_a_real!r})",
    )

    print("  G31b: 'rounds/0008/evidence/' (empty prefix, goal-relative) is NOT flagged")
    note_b = verify_protocol.scope_lock_round_path_mismatch(
        "rounds/0008/evidence/", th0026_round_dir, th0026_project
    )
    check(
        note_b is None,
        f"G31b: an empty span prefix ('rounds/0008/evidence/') is a suffix of anything, so it "
        f"is not flagged -- every base verify_round already tries (got {note_b!r})",
    )
    note_b_mutation = verify_protocol.scope_lock_round_path_mismatch(
        ".harnessloop/rounds/0008/", th0026_round_dir, th0026_project
    )
    check(
        note_b_mutation is not None,
        "G31b mutation control: prefixing the SAME round number with the wrong "
        f"'.harnessloop' segment flips it to flagged (got {note_b_mutation!r})",
    )

    print("  G31c: 'goals/<slug>/rounds/0008/' (goal-relative form) is NOT flagged")
    note_c = verify_protocol.scope_lock_round_path_mismatch(
        f"goals/{th0026_goal_slug}/rounds/0008/", th0026_round_dir, th0026_project
    )
    check(
        note_c is None,
        f"G31c: 'goals/{th0026_goal_slug}/rounds/0008/' is a genuine path-segment suffix of "
        f"this round's real prefix ('.harnessloop/goals/{th0026_goal_slug}') and so is not "
        f"flagged (got {note_c!r})",
    )

    print("  G31d: segment comparison, not string comparison -- 'xgoals/<slug>/rounds/0008/' MUST be flagged")
    naive_span_prefix = f"xgoals/{th0026_goal_slug}"
    naive_relative_form = f"goals/{th0026_goal_slug}"
    check(
        naive_span_prefix.endswith(naive_relative_form),
        "G31d fixture sanity: a naive raw-string .endswith check on the span's own prefix "
        f"text really would (wrongly) read '{naive_span_prefix}' as already containing the "
        f"correct relative suffix '{naive_relative_form}' -- proving this fixture actually "
        "distinguishes segment-wise from string-wise comparison, not a vacuous case where "
        "both approaches agree",
    )
    note_d = verify_protocol.scope_lock_round_path_mismatch(
        f"xgoals/{th0026_goal_slug}/rounds/0008/", th0026_round_dir, th0026_project
    )
    check(
        note_d is not None,
        f"G31d: 'xgoals/{th0026_goal_slug}/rounds/0008/' MUST be flagged -- 'xgoals' and "
        "'goals' are different path segments, not one a substring of the other at a segment "
        f"boundary; a string-endswith implementation would have missed this (got {note_d!r})",
    )

    print("  G31e: span names a DIFFERENT round (rounds/0007) -> NOT flagged (OUT list item 2)")
    note_e = verify_protocol.scope_lock_round_path_mismatch(
        "rounds/0007/", th0026_round_dir, th0026_project
    )
    check(
        note_e is None,
        "G31e: round 0008's scope-lock citing 'rounds/0007/' (a different round's number) is "
        "not flagged -- this rule cannot tell a deliberate cross-round reference from a typo, "
        f"and does not try (registered OUT-list boundary, not a missed case) (got {note_e!r})",
    )

    print("  G31f: real verify_project() integration -- hint-only, exit code and violations untouched")
    g31f_root = REPO_ROOT / ".tmp" / f"verify-fixture-g31f-{uuid.uuid4().hex}"
    g31f_round_dir = g31f_root / ".harnessloop" / "goals" / "20260101-001-g31f" / "rounds" / "0008"
    try:
        g31f_round_dir.mkdir(parents=True)
        (g31f_round_dir / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n- `.harnessloop/rounds/0008/`\n",
            encoding="utf-8",
        )
        violations, coverage = verify_protocol.verify_project(g31f_root)
        check(
            not violations,
            "G31f: a project with ONLY the TH-0026 mismatch (no other artifacts) produces "
            f"zero violations -- the hint never enters the violations list (got {violations})",
        )
        check(
            coverage.get("rounds_scope_lock_round_path_mismatch") == 1,
            "G31f: coverage counts exactly 1 round with the mismatch "
            f"(got {coverage.get('rounds_scope_lock_round_path_mismatch')!r})",
        )
    finally:
        shutil.rmtree(g31f_root, ignore_errors=True)

    print("  G31g: coverage accumulates across rounds -- two mismatched rounds -> count 2")
    g31g_root = REPO_ROOT / ".tmp" / f"verify-fixture-g31g-{uuid.uuid4().hex}"
    try:
        for g31g_round_name in ("0008", "0009"):
            g31g_round_dir = (
                g31g_root / ".harnessloop" / "goals" / "20260101-001-g31g" / "rounds" / g31g_round_name
            )
            g31g_round_dir.mkdir(parents=True)
            (g31g_round_dir / "scope-lock.md").write_text(
                "# Scope Lock\n\n## Allowed Changes\n\n"
                f"- `.harnessloop/rounds/{g31g_round_name}/`\n",
                encoding="utf-8",
            )
        violations, coverage = verify_protocol.verify_project(g31g_root)
        check(
            not violations,
            f"G31g: both mismatched rounds still produce zero violations (got {violations})",
        )
        check(
            coverage.get("rounds_scope_lock_round_path_mismatch") == 2
            and coverage.get("rounds") == 2,
            "G31g: coverage sums the per-round mismatch flag across rounds (both rounds hit "
            f"-> 2), not just the last round checked (got {coverage.get('rounds_scope_lock_round_path_mismatch')!r} "
            f"of {coverage.get('rounds')!r} rounds)",
        )
    finally:
        shutil.rmtree(g31g_root, ignore_errors=True)

    # -------------------------------------------------------------------
    # G32: batch 2 of docs/loop-stop-record-spec-20260728.md (Appendix F's
    # reversed direction) -- the loop-predecessor gate
    # (`check_loop_predecessor_declaration`) and the loop-continuation
    # record gate (`check_loop_continuation_declaration`). Every letter is a
    # paired mutation exactly like G25/G26 above: a fixture asserted to land
    # on verdict X under the real implementation, then a minimal, specific
    # change to that SAME fixture asserted to flip the verdict -- proving
    # each check discriminates on the exact condition it claims to.
    # -------------------------------------------------------------------

    def _loop_project(tmp_root: Path) -> Path:
        return tmp_root / "project"

    def _loop_round_dir(project: Path, round_name: str, goal: str = "20260101-001-loop") -> Path:
        return project / ".harnessloop" / "goals" / goal / "rounds" / round_name

    def _loop_round(project: Path, round_name: str, goal: str = "20260101-001-loop") -> Path:
        """Create a minimal, real round directory -- scope-lock.md present
        and parseable -- so this gate's own unrelated `missing-scope-lock` /
        `unparseable-allowed-changes` noise never contaminates a G32
        assertion (every G32 assertion below filters to `loop-` kinds via
        `_loop_kinds`, but keeping the fixtures clean is cheap and avoids
        depending on that filter alone)."""
        round_dir = _loop_round_dir(project, round_name, goal)
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "scope-lock.md").write_text(
            "# Scope Lock\n\n## Allowed Changes\n\n"
            f"- `.harnessloop/goals/{goal}/rounds/{round_name}/`\n",
            encoding="utf-8",
        )
        return round_dir

    def _loop_write_decision(
        project: Path, round_name: str, text: str, goal: str = "20260101-001-loop"
    ) -> None:
        (_loop_round_dir(project, round_name, goal) / "decision.md").write_text(
            text, encoding="utf-8"
        )

    def _loop_kinds(violations: list[dict]) -> set[str]:
        return {v["kind"] for v in violations if v["kind"].startswith("loop-")}

    print(
        "  G32a: Predecessor: 0003 (round 0003 exists, this round 0007) -> green; "
        "deleting round 0003 -> loop-predecessor-missing"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32a-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0003")
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Predecessor: 0003\n")
        violations, coverage = verify_protocol.verify_project(project)
        check(
            not _loop_kinds(violations),
            "G32a: Predecessor: 0003 with round 0003 existing under the same goal's "
            f"rounds/ -> zero loop-* violations (got {sorted(_loop_kinds(violations))})",
        )
        check(
            coverage.get("rounds_predecessor_declared") == 1,
            "G32a: rounds_predecessor_declared counts exactly 1 round declaring "
            f"Predecessor (got {coverage.get('rounds_predecessor_declared')!r})",
        )

        shutil.rmtree(_loop_round_dir(project, "0003"))
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "loop-predecessor-missing" in _loop_kinds(violations),
            "G32a mutation control: deleting round 0003's directory (round 0007's "
            "decision.md left byte-for-byte untouched) turns round 0007 red with "
            "loop-predecessor-missing -- proves G32a's greenness depended on 0003 "
            "actually existing on disk, not a vacuous always-pass path",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print(
        "  G32b: Predecessor: 0009 (forward of round 0007) -> loop-predecessor-not-backward; "
        "changing to 0003 -> green"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32b-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0003")
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Predecessor: 0009\n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "loop-predecessor-not-backward" in _loop_kinds(violations),
            "G32b: Predecessor: 0009 while this round is 0007 (0009 > 0007, a forward "
            f"reference) -> loop-predecessor-not-backward (got {sorted(_loop_kinds(violations))})",
        )
        check(
            "loop-predecessor-missing" not in _loop_kinds(violations),
            "G32b: the not-backward violation fires even though round 0009 does not "
            "exist anywhere in this fixture -- proves the arithmetic check runs before, "
            "and independently of, the filesystem existence check",
        )

        _loop_write_decision(project, "0007", "# Decision\n\n- Predecessor: 0003\n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            not _loop_kinds(violations),
            "G32b mutation control: changing ONLY the Predecessor value to 0003 (a real, "
            f"backward, existing round) clears the violation (got {sorted(_loop_kinds(violations))})",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print(
        "  G32c: Predecessor: 0007 (self-reference, round 0007) -> "
        "loop-predecessor-not-backward (proves strict <, not <=)"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32c-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Predecessor: 0007\n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "loop-predecessor-not-backward" in _loop_kinds(violations),
            "G32c: a round citing itself as its own Predecessor -> "
            "loop-predecessor-not-backward, not silently accepted merely because the "
            f"named round trivially 'exists' (it is this round itself) (got {sorted(_loop_kinds(violations))})",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print("  G32d: Predecessor: abc (not four digits) -> loop-predecessor-invalid-value")
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32d-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Predecessor: abc\n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "loop-predecessor-invalid-value" in _loop_kinds(violations),
            "G32d: Predecessor: abc is not exactly four digits -> "
            f"loop-predecessor-invalid-value, fail-closed (got {sorted(_loop_kinds(violations))})",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print(
        "  G32e: no Predecessor field at all -> zero loop-predecessor-* violations "
        "(migration-silent); writing a bad value on the SAME fixture turns it red"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32e-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Verdict: pass\n")
        violations, coverage = verify_protocol.verify_project(project)
        predecessor_kinds = {k for k in _loop_kinds(violations) if k.startswith("loop-predecessor-")}
        check(
            not predecessor_kinds,
            "G32e: a decision.md with no `- Predecessor:` line at all -> zero "
            f"loop-predecessor-* violations (migration-silent, got {sorted(predecessor_kinds)})",
        )
        check(
            coverage.get("rounds_predecessor_declared") == 0,
            "G32e: rounds_predecessor_declared stays 0 when the field was never "
            f"written (got {coverage.get('rounds_predecessor_declared')!r})",
        )

        _loop_write_decision(project, "0007", "# Decision\n\n- Verdict: pass\n- Predecessor: 9999\n")
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "loop-predecessor-not-backward" in _loop_kinds(violations),
            "G32e reverse mutation: adding a bad Predecessor value (9999, forward of "
            "round 0007) to the SAME otherwise-unchanged decision.md immediately turns "
            "it red -- proves the earlier green was a real absence-check, not a vacuous "
            "always-pass path that never actually looks at the field",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print(
        "  G32f: Loop continuation: stopped: goal-achieved -> green; "
        "stopped: 瞎编的理由 (not in the enum) -> loop-continuation-invalid-value"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32f-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0007")
        _loop_write_decision(
            project, "0007", "# Decision\n\n- Loop continuation: stopped: goal-achieved\n"
        )
        violations, coverage = verify_protocol.verify_project(project)
        check(
            not _loop_kinds(violations),
            "G32f: stopped: goal-achieved (a real enum member) -> zero loop-* "
            f"violations (got {sorted(_loop_kinds(violations))})",
        )
        check(
            coverage.get("rounds_stop_recorded") == 1,
            f"G32f: rounds_stop_recorded counts this round (got {coverage.get('rounds_stop_recorded')!r})",
        )

        _loop_write_decision(
            project, "0007", "# Decision\n\n- Loop continuation: stopped: 瞎编的理由\n"
        )
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "loop-continuation-invalid-value" in _loop_kinds(violations),
            "G32f: stopped: 瞎编的理由 (a made-up reason with no whitespace, structurally "
            "shaped like a reason token but not a member of the enum) -> "
            f"loop-continuation-invalid-value (got {sorted(_loop_kinds(violations))}) -- this "
            "gate checks enum membership only, never whether a reason 'sounds plausible'",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print(
        "  G32g: Loop continuation: stopped: unjustified-stop -> green (never judged "
        "red) and rounds_stop_unjustified == 1"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32g-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0007")
        _loop_write_decision(
            project, "0007", "# Decision\n\n- Loop continuation: stopped: unjustified-stop\n"
        )
        violations, coverage = verify_protocol.verify_project(project)
        check(
            not _loop_kinds(violations),
            "G32g: stopped: unjustified-stop is a LEGAL enum member -- the spec argues at "
            "length (§1.2/§3.2) that a mechanical gate cannot distinguish an honest "
            "unjustified stop from one dressed up in a compliant-sounding reason, so "
            f"judging this one red would only punish the honest label (got {sorted(_loop_kinds(violations))})",
        )
        check(
            coverage.get("rounds_stop_unjustified") == 1
            and coverage.get("rounds_stop_recorded") == 1,
            "G32g: rounds_stop_unjustified counts this round exactly once, as a strict "
            f"subset of rounds_stop_recorded (got stop_unjustified="
            f"{coverage.get('rounds_stop_unjustified')!r}, stop_recorded="
            f"{coverage.get('rounds_stop_recorded')!r})",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print(
        "  G32h: Loop continuation: stopped: goal-achieved — 因为目标达成了 "
        "(free-text note after the reason) -> green"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32h-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0007")
        _loop_write_decision(
            project,
            "0007",
            "# Decision\n\n- Loop continuation: stopped: goal-achieved — 因为目标达成了\n",
        )
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            not _loop_kinds(violations),
            "G32h: a valid reason followed by a free-text note after ' — ' -> green; "
            f"the note's content is never itself validated (got {sorted(_loop_kinds(violations))})",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print(
        "  G32i: a fenced bad Predecessor value must never shadow the real, unfenced "
        "declaration (proves the new field really routes through _uncoded_lines)"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32i-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0003")
        _loop_round(project, "0007")
        fenced_decision = (
            "# Decision\n\n"
            "Example of a bad declaration (do not do this):\n\n"
            "```\n"
            "- Predecessor: 0009\n"
            "```\n\n"
            "- Predecessor: 0003\n"
        )
        _loop_write_decision(project, "0007", fenced_decision)
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            not _loop_kinds(violations),
            "G32i: the fenced `- Predecessor: 0009` (bad -- forward reference) must "
            "never outrank the real, unfenced `- Predecessor: 0003` (good) that follows "
            f"it -- first-occurrence-wins only applies among UNFENCED lines (got {sorted(_loop_kinds(violations))})",
        )

        unfenced_decision = (
            "# Decision\n\n"
            "Example of a bad declaration (do not do this):\n\n"
            "- Predecessor: 0009\n\n"
            "- Predecessor: 0003\n"
        )
        _loop_write_decision(project, "0007", unfenced_decision)
        violations, _coverage = verify_protocol.verify_project(project)
        check(
            "loop-predecessor-not-backward" in _loop_kinds(violations),
            "G32i mutation control: removing ONLY the two fence-marker lines (same two "
            "Predecessor lines, same order, same everything else) turns round 0007 red "
            "-- first occurrence now wins on the formerly-fenced 0009 line, proving "
            "G32i's greenness genuinely depended on the fence and not on some other "
            "property of the fixture",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    print(
        "  G32j: Loop continuation: stopped: goal-achieved。 (trailing full-width period) "
        "-> loop-continuation-invalid-value, fail-closed, and no other loop-* kind fires "
        "alongside it"
    )
    g32_root = REPO_ROOT / ".tmp" / f"verify-fixture-g32j-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g32_root)
        _loop_round(project, "0007")
        _loop_write_decision(
            project, "0007", "# Decision\n\n- Loop continuation: stopped: goal-achieved。\n"
        )
        violations, coverage = verify_protocol.verify_project(project)
        loop_kinds = _loop_kinds(violations)
        check(
            loop_kinds == {"loop-continuation-invalid-value"},
            "G32j: a trailing full-width period (U+3002) does not normalize to any enum "
            "member (strip+lower only, no punctuation stripped) -> "
            "loop-continuation-invalid-value, fail-closed -- never silently read as "
            "absent -- and it is the ONLY loop-* kind present, proving the continuation "
            "gate's fail-closed branch is independent of the predecessor gate "
            f"(got {sorted(loop_kinds)})",
        )
        check(
            coverage.get("rounds_stop_recorded") == 0,
            "G32j: an unparsable value is never counted in rounds_stop_recorded (got "
            f"{coverage.get('rounds_stop_recorded')!r})",
        )
    finally:
        shutil.rmtree(g32_root, ignore_errors=True)

    # G33: batch 3 of docs/loop-stop-record-spec-20260728.md (§4/§5, restated
    # by that spec's Appendix B.1/B.2/F.3) -- the loop-autocontinue anomaly
    # gate (`check_loop_autocontinue_anomaly`). Reuses G32's `_loop_project` /
    # `_loop_round` / `_loop_round_dir` / `_loop_write_decision` / `_loop_kinds`
    # closures above (same fixture family, same default goal
    # "20260101-001-loop") plus three new small helpers for the two
    # project-level files this gate reads: `.harnessloop/state/control-
    # contract.md`'s three canonical fields and `.harnessloop/state/evidence-
    # index.md`'s table. Every letter is a paired mutation exactly like
    # G32/G25/G26 above.
    # -------------------------------------------------------------------

    def _g33_write_contract(project: Path, profile: str, positive: str) -> None:
        contract = project / ".harnessloop" / "state" / "control-contract.md"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text(
            "# Control Contract\n\n"
            "## Auto-Continue\n\n"
            f"- Profile: {profile}\n"
            f"- Auto-continue on positive: {positive}\n"
            "- Auto-continue on negative/neutral remediation: no\n\n"
            "Allowed when:\n\n"
            "- Feedback class: positive\n"
            "- Evidence health: no stale\n"
            "- Environment self-check: pass\n"
            "- Open handoffs: none\n"
            "- Human confirmation: not required\n",
            encoding="utf-8",
        )

    def _g33_write_contract_no_profile(project: Path) -> None:
        contract = project / ".harnessloop" / "state" / "control-contract.md"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text(
            "# Control Contract\n\n"
            "## Auto-Continue\n\n"
            "Allowed when:\n\n"
            "- Feedback class: positive\n"
            "- Evidence health: no stale\n"
            "- Environment self-check: pass\n"
            "- Open handoffs: none\n"
            "- Human confirmation: not required\n",
            encoding="utf-8",
        )

    def _g33_write_contract_raw(project: Path, text: str) -> None:
        contract = project / ".harnessloop" / "state" / "control-contract.md"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text(text, encoding="utf-8")

    def _g33_evidence_row(evidence_id: str, health: str) -> str:
        # 14 cells, matching evidence-index-template.md's 14-column header
        # verbatim; only Evidence ID and Artifact health vary per fixture.
        cells = [
            evidence_id, "static", "p", "a", "f", "t", "v", "no", "yes",
            health, "s", "eff", "rep", "internal",
        ]
        return "| " + " | ".join(cells) + " |"

    def _g33_write_evidence_index(project: Path, rows: list) -> None:
        path = project / ".harnessloop" / "state" / "evidence-index.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# Evidence Index\n\n"
            "| Evidence ID | Type | Path | Applies to | Freshness requirement | "
            "Observed timestamp | Validation method | Channel parameter references | "
            "Citation required | Artifact health | Claim support | Acceptance effect | "
            "Reproducibility | Sensitivity |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        )
        path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")

    print(
        "  G33a: Profile=standard + Auto-continue positive=yes + Feedback positive + "
        "evidence-index all valid -> loop_autocontinue_anomaly=1, no violations, exit "
        "code unaffected; Feedback negative on the SAME fixture -> 0"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33a-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: positive\n")
        _g33_write_contract(project, "standard", "yes")
        _g33_write_evidence_index(project, [_g33_evidence_row("E1", "valid")])
        violations, coverage = verify_protocol.verify_project(project)
        check(
            "loop-contract-profile-missing" not in _loop_kinds(violations),
            "G33a: this fixture's contract carries a `- Profile:` field -> no "
            f"profile-missing violation (got {sorted(_loop_kinds(violations))})",
        )
        check(
            coverage.get("loop_autocontinue_anomaly") == 1,
            "G33a: Profile=standard, Auto-continue on positive=yes, Feedback=positive, "
            "evidence-index all valid -> loop_autocontinue_anomaly==1 (got "
            f"{coverage.get('loop_autocontinue_anomaly')!r})",
        )
        check(
            coverage.get("loop_anomaly_skipped_unparsable") == 0,
            "G33a: every precondition was mechanically determinable -> "
            f"loop_anomaly_skipped_unparsable==0 (got {coverage.get('loop_anomaly_skipped_unparsable')!r})",
        )

        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: negative\n")
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 0,
            "G33a mutation control: changing ONLY Feedback to negative clears the "
            f"anomaly (got {coverage.get('loop_autocontinue_anomaly')!r}) -- proves the "
            "count genuinely depended on Feedback: positive, not a vacuous always-1 path",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)

    print(
        "  G33b: Profile=strict -> loop_autocontinue_anomaly=0 (a determinate exclusion, "
        "not a skip); changing to standard on the SAME fixture -> 1"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33b-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: positive\n")
        _g33_write_contract(project, "strict", "yes")
        _g33_write_evidence_index(project, [_g33_evidence_row("E1", "valid")])
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 0,
            "G33b: Profile=strict is excluded from the anomaly trigger even though every "
            f"other condition holds (got {coverage.get('loop_autocontinue_anomaly')!r})",
        )
        check(
            coverage.get("loop_anomaly_skipped_unparsable") == 0,
            "G33b: `strict` is a recognized, known value -- this is a determinate 'no', "
            f"never an unparsable skip (got {coverage.get('loop_anomaly_skipped_unparsable')!r})",
        )

        _g33_write_contract(project, "standard", "yes")
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 1,
            "G33b mutation control: changing ONLY Profile to standard on the SAME "
            f"fixture flips the anomaly on (got {coverage.get('loop_autocontinue_anomaly')!r})",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)

    print(
        "  G33c: Auto-continue on positive=no -> loop_autocontinue_anomaly=0 even "
        "though Profile/Feedback/evidence all otherwise qualify"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33c-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: positive\n")
        _g33_write_contract(project, "standard", "no")
        _g33_write_evidence_index(project, [_g33_evidence_row("E1", "valid")])
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 0,
            "G33c: Auto-continue on positive: no -> anomaly never fires (got "
            f"{coverage.get('loop_autocontinue_anomaly')!r})",
        )
        check(
            coverage.get("loop_anomaly_skipped_unparsable") == 0,
            "G33c: `no` is a recognized, known value -- determinate 'no', not a skip "
            f"(got {coverage.get('loop_anomaly_skipped_unparsable')!r})",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)

    print(
        "  G33d: evidence-index has a row with Artifact health=missing -> "
        "loop_autocontinue_anomaly=0 (determinate, not a skip); changing that row to "
        "valid on the SAME fixture -> 1"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33d-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: positive\n")
        _g33_write_contract(project, "standard", "yes")
        _g33_write_evidence_index(
            project, [_g33_evidence_row("E1", "valid"), _g33_evidence_row("E2", "missing")]
        )
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 0,
            "G33d: evidence-index.md has one row with Artifact health=missing -> not "
            f"every row is valid -> loop_autocontinue_anomaly==0 (got {coverage.get('loop_autocontinue_anomaly')!r})",
        )
        check(
            coverage.get("loop_anomaly_skipped_unparsable") == 0,
            "G33d: the table parsed fine and every value was a recognized enum member "
            "-- health=missing is a determinate 'not all valid', not an unparsable skip "
            f"(got {coverage.get('loop_anomaly_skipped_unparsable')!r})",
        )

        _g33_write_evidence_index(
            project, [_g33_evidence_row("E1", "valid"), _g33_evidence_row("E2", "valid")]
        )
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 1,
            "G33d mutation control: changing ONLY E2's Artifact health to valid on the "
            f"SAME fixture flips the anomaly on (got {coverage.get('loop_autocontinue_anomaly')!r})",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)

    print(
        "  G33e: evidence-index.md does not exist at all -> loop_autocontinue_anomaly=0 "
        "AND loop_anomaly_skipped_unparsable=1 (the skip is visible, not silent)"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33e-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: positive\n")
        _g33_write_contract(project, "standard", "yes")
        # Deliberately never call _g33_write_evidence_index -- evidence-index.md
        # does not exist in this fixture at all.
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 0,
            "G33e: a missing evidence-index.md means the evidence-health precondition "
            f"cannot be determined -> loop_autocontinue_anomaly==0 (got {coverage.get('loop_autocontinue_anomaly')!r})",
        )
        check(
            coverage.get("loop_anomaly_skipped_unparsable") == 1,
            "G33e: with every OTHER precondition (Profile/Auto-continue on positive/"
            "Feedback) mechanically determinable and true, a missing evidence-index.md "
            "is the ONLY undeterminable condition -- this must show up as "
            f"loop_anomaly_skipped_unparsable==1 (got {coverage.get('loop_anomaly_skipped_unparsable')!r}), "
            "proving 'this could not be judged' is visible, not silently folded into an "
            "ordinary non-trigger",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)

    print(
        "  G33f: contract has no `- Profile:` field and no round anywhere has ever "
        "declared `Loop continuation:`/`Predecessor:` -> zero loop-* violations "
        "(mechanism not yet activated)"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33f-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: positive\n")
        _g33_write_contract_no_profile(project)
        _g33_write_evidence_index(project, [_g33_evidence_row("E1", "valid")])
        violations, coverage = verify_protocol.verify_project(project)
        check(
            "loop-contract-profile-missing" not in _loop_kinds(violations),
            "G33f: no round anywhere in this project has ever declared `Loop "
            "continuation:` or `Predecessor:` -- the mechanism is not yet activated, so "
            f"a missing `Profile:` field has zero effect (got {sorted(_loop_kinds(violations))})",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)

    print(
        "  G33g: same missing `- Profile:`, but round 0003 declares `- Predecessor: "
        "0001` (no `Loop continuation:` anywhere) -> loop-contract-profile-missing; "
        "adding `- Profile:` on the SAME fixture clears it"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33g-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0001")
        _loop_round(project, "0003")
        _loop_write_decision(project, "0001", "# Decision\n\n- Feedback: positive\n")
        _loop_write_decision(
            project, "0003", "# Decision\n\n- Predecessor: 0001\n- Feedback: positive\n"
        )
        _g33_write_contract_no_profile(project)
        _g33_write_evidence_index(project, [_g33_evidence_row("E1", "valid")])
        violations, coverage = verify_protocol.verify_project(project)
        check(
            "loop-contract-profile-missing" in _loop_kinds(violations),
            "G33g: round 0003 declares `- Predecessor: 0001` -- no round anywhere "
            "declares `- Loop continuation:` -- this alone must count as 'activated', "
            "per Appendix F's inclusion of Predecessor alongside Loop continuation "
            f"(got {sorted(_loop_kinds(violations))})",
        )

        _g33_write_contract(project, "standard", "yes")
        violations, coverage = verify_protocol.verify_project(project)
        check(
            "loop-contract-profile-missing" not in _loop_kinds(violations),
            "G33g mutation control: writing a `- Profile:` field on the SAME "
            f"otherwise-unchanged fixture clears the violation (got {sorted(_loop_kinds(violations))})",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)

    print(
        "  G33h: a fenced `- Profile: strict` example must never outrank the real, "
        "unfenced `- Profile: standard` that follows it"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33h-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0007")
        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: positive\n")
        fenced_contract = (
            "# Control Contract\n\n"
            "## Auto-Continue\n\n"
            "Example of a bad declaration (do not do this):\n\n"
            "```\n"
            "- Profile: strict\n"
            "```\n\n"
            "- Profile: standard\n"
            "- Auto-continue on positive: yes\n"
            "- Auto-continue on negative/neutral remediation: no\n\n"
            "Allowed when:\n\n"
            "- Feedback class: positive\n"
        )
        _g33_write_contract_raw(project, fenced_contract)
        _g33_write_evidence_index(project, [_g33_evidence_row("E1", "valid")])
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 1,
            "G33h: the fenced `- Profile: strict` example must never shadow the real, "
            f"unfenced `- Profile: standard` that follows it (got {coverage.get('loop_autocontinue_anomaly')!r})",
        )

        unfenced_contract = (
            "# Control Contract\n\n"
            "## Auto-Continue\n\n"
            "Example of a bad declaration (do not do this):\n\n"
            "- Profile: strict\n\n"
            "- Profile: standard\n"
            "- Auto-continue on positive: yes\n"
            "- Auto-continue on negative/neutral remediation: no\n\n"
            "Allowed when:\n\n"
            "- Feedback class: positive\n"
        )
        _g33_write_contract_raw(project, unfenced_contract)
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 0,
            "G33h mutation control: removing ONLY the fence markers (same two Profile "
            "lines, same order, same everything else) makes the now-first `- Profile: "
            f"strict` line win instead -> the anomaly clears (got {coverage.get('loop_autocontinue_anomaly')!r})",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)

    print(
        "  G33i: only the latest round is ever evaluated -- an older round satisfying "
        "every condition does not count when the newest round's Feedback is negative"
    )
    g33_root = REPO_ROOT / ".tmp" / f"verify-fixture-g33i-{uuid.uuid4().hex}"
    try:
        project = _loop_project(g33_root)
        _loop_round(project, "0003")
        _loop_round(project, "0007")
        _loop_write_decision(project, "0003", "# Decision\n\n- Feedback: positive\n")
        _loop_write_decision(project, "0007", "# Decision\n\n- Feedback: negative\n")
        _g33_write_contract(project, "standard", "yes")
        _g33_write_evidence_index(project, [_g33_evidence_row("E1", "valid")])
        violations, coverage = verify_protocol.verify_project(project)
        check(
            coverage.get("loop_autocontinue_anomaly") == 0,
            "G33i: round 0003 (older) satisfies every anomaly condition, but round "
            "0007 is this goal's latest round and its Feedback is negative -- OUT-list "
            "item 4 (harnessloop-loop/SKILL.md): anomaly only ever looks at the newest "
            "round, never retroactively judges an earlier one (got "
            f"{coverage.get('loop_autocontinue_anomaly')!r})",
        )
    finally:
        shutil.rmtree(g33_root, ignore_errors=True)


def validate_round_cost_smoke() -> None:
    print("[8/9] Round cost settlement smoke test (round_cost.py)")
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
    print("[9/9] Claude strict plugin validation")
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
    validate_version_consistency()
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
