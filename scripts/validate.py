#!/usr/bin/env python3
"""Cross-platform Harnessloop repository validation.

Checks, in order:
1. Manifest and marketplace invariants (Codex + Claude).
2. Init smoke test (skeleton creation, intake packet).
3. Secrets smoke test (channel-params store, gitignore protection, no values).
4. Documentation skeleton consistency against init_project.py (single source of truth).
5. Mechanical protocol gates (verify_protocol.py) on examples/mock-project,
   including negative fixtures that must fail.
6. Round cost settlement smoke test (round_cost.py) on a synthetic transcript.
7. Claude strict plugin validation (skippable via HARNESSLOOP_SKIP_CLAUDE=1
   for environments without the claude CLI, e.g. bare CI runners).

Exit code 0 = all passed.
"""

from __future__ import annotations

import json
import os
import shutil
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
    print("[1/7] Manifests and marketplace entries")
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
    print("[2/7] Init smoke test")
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


def validate_secrets_smoke() -> None:
    print("[3/7] Secrets smoke test")
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
    print("[4/7] Documentation skeleton consistency (source of truth: init_project.py)")
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
    print("[5/7] Mechanical protocol gates (verify_protocol.py)")
    mock_project = REPO_ROOT / "examples" / "mock-project"
    violations = verify_protocol.verify_project(mock_project)
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
        violations = verify_protocol.verify_project(fixture_root)
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
        violations = verify_protocol.verify_project(fixture_root)
        kinds = {v["kind"] for v in violations}
        check(
            "unparseable-allowed-changes" not in kinds and "scope-lock-violation" not in kinds,
            "verify accepts template-style table scope-locks",
        )
    finally:
        shutil.rmtree(fixture_root, ignore_errors=True)


def validate_round_cost_smoke() -> None:
    print("[6/7] Round cost settlement smoke test (round_cost.py)")
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
    print("[7/7] Claude strict plugin validation")
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
