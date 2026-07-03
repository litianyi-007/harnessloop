#!/usr/bin/env python3
"""Settle per-round token cost from Claude Code session transcripts.

Reads the project's transcript files (JSONL under
~/.claude/projects/<escaped-project-path>/), aggregates API usage recorded on
assistant turns since the last settlement marker, and prints a markdown
`## Cost` section ready to paste into the round's round-summary.md.

The computation is fully local and deterministic — transcripts must never be
read into the model context; only this script's short summary is.

Attribution heuristic: an assistant turn whose message content mentions
`.harnessloop` is counted as protocol-attributed. This is a heuristic, not an
exact split; the output labels it as such.

Cost estimation is optional: create `.harnessloop/local/cost-prices.json`
with USD-per-million-token rates, e.g.
    {"input": 3.0, "cache_write": 3.75, "cache_read": 0.3, "output": 15.0}
No model prices are baked into this script.

The settlement marker (`.harnessloop/local/cost-marker.json`) stores how many
transcript lines were already counted, so each run reports only the window
since the previous run. Multi-session rounds are covered: all transcript
files for the project are tracked independently.

Exit codes: 0 = settled, 2 = transcript directory not found or usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

MARKER_REL = Path(".harnessloop/local/cost-marker.json")
PRICES_REL = Path(".harnessloop/local/cost-prices.json")
PRICE_KEYS = ("input", "cache_write", "cache_read", "output")


def default_transcript_dir(project: Path) -> Path:
    escaped = re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))
    return Path.home() / ".claude" / "projects" / escaped


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def load_prices(project: Path) -> dict | None:
    prices = load_json(project / PRICES_REL)
    if all(isinstance(prices.get(key), (int, float)) for key in PRICE_KEYS):
        return prices
    return None


def settle(transcript_dir: Path, marker: dict) -> tuple[dict, dict]:
    """Aggregate usage after each file's marker offset; return (totals, new offsets)."""
    offsets = marker.get("files", {}) if isinstance(marker.get("files"), dict) else {}
    totals = {
        "turns": 0,
        "input": 0,
        "cache_write": 0,
        "cache_read": 0,
        "output": 0,
        "protocol_turns": 0,
        "protocol_output": 0,
        "files": 0,
    }
    new_offsets: dict[str, int] = {}

    for transcript in sorted(transcript_dir.glob("*.jsonl")):
        start = offsets.get(transcript.name, 0)
        if not isinstance(start, int) or start < 0:
            start = 0
        line_count = 0
        with transcript.open(encoding="utf-8", errors="replace") as fh:
            for line_count, line in enumerate(fh, start=1):
                if line_count <= start:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "assistant":
                    continue
                message = record.get("message") or {}
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                totals["turns"] += 1
                totals["input"] += usage.get("input_tokens", 0) or 0
                totals["cache_write"] += usage.get("cache_creation_input_tokens", 0) or 0
                totals["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
                output_tokens = usage.get("output_tokens", 0) or 0
                totals["output"] += output_tokens
                content_blob = json.dumps(message.get("content"), ensure_ascii=False)
                if ".harnessloop" in content_blob:
                    totals["protocol_turns"] += 1
                    totals["protocol_output"] += output_tokens
        # Next settlement starts after the last line seen now; a shrunk or
        # replaced file naturally resets to its current length.
        new_offsets[transcript.name] = line_count
        totals["files"] += 1

    return totals, new_offsets


def render(totals: dict, prices: dict | None) -> str:
    pct = (
        f"{totals['protocol_output'] * 100 // totals['output']}% of output"
        if totals["output"]
        else "n/a"
    )
    lines = [
        "## Cost",
        "",
        f"- Transcript window: {totals['files']} file(s), {totals['turns']} assistant turn(s) since last settlement",
        f"- Input tokens: {totals['input']:,}",
        f"- Cache write tokens: {totals['cache_write']:,}",
        f"- Cache read tokens: {totals['cache_read']:,}",
        f"- Output tokens: {totals['output']:,}",
        f"- Protocol-attributed (heuristic): {totals['protocol_turns']}/{totals['turns']} turns, "
        f"{totals['protocol_output']:,} output tokens ({pct})",
    ]
    if prices:
        cost = (
            totals["input"] * prices["input"]
            + totals["cache_write"] * prices["cache_write"]
            + totals["cache_read"] * prices["cache_read"]
            + totals["output"] * prices["output"]
        ) / 1_000_000
        lines.append(f"- Estimated cost: ${cost:.4f} (rates from {PRICES_REL.as_posix()})")
    else:
        lines.append(
            f"- Estimated cost: unavailable (create {PRICES_REL.as_posix()} with USD-per-Mtok rates: "
            '{"input": .., "cache_write": .., "cache_read": .., "output": ..})'
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle per-round token cost from session transcripts.")
    parser.add_argument("--project", "-p", default=".", help="Target project directory. Defaults to current directory.")
    parser.add_argument("--transcript-dir", help="Transcript directory override (defaults to ~/.claude/projects/<escaped-project-path>).")
    parser.add_argument("--dry-run", action="store_true", help="Report without updating the settlement marker.")
    parser.add_argument("--reset", action="store_true", help="Move the marker to end-of-transcripts without reporting a window.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of markdown.")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    transcript_dir = Path(args.transcript_dir).resolve() if args.transcript_dir else default_transcript_dir(project)
    if not transcript_dir.is_dir():
        print(f"Transcript directory not found: {transcript_dir}", file=sys.stderr)
        print("Cost unavailable for this round; record the reason in round-summary.md.", file=sys.stderr)
        return 2

    marker_path = project / MARKER_REL
    marker = {} if args.reset else load_json(marker_path)
    totals, new_offsets = settle(transcript_dir, marker if not args.reset else {})

    if not args.dry_run:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps(
                {"version": 1, "updated": datetime.now().isoformat(timespec="seconds"), "files": new_offsets},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if args.reset:
        print(f"Marker reset to end of {totals['files']} transcript file(s): {marker_path}")
        return 0

    if args.json:
        print(json.dumps({"project": str(project), "transcript_dir": str(transcript_dir), **totals}, indent=2))
    else:
        print(render(totals, load_prices(project)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
