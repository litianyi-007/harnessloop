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

Message-id dedup: Claude Code writes one JSONL line per content block of an
assistant message (thinking/tool_use/text/...), and every line for the same
`message.id` repeats that message's full usage snapshot. Lines are grouped by
`message.id` and each id's usage is counted exactly once (see `settle()` for
the dedup and cross-settlement-window contract, including how the marker
carries forward a message that is still being written when this script runs
mid-turn).

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


USAGE_KEYS = PRICE_KEYS  # same four cost categories; separate name for readability at call sites


def _zero_usage() -> dict:
    return {key: 0 for key in USAGE_KEYS}


def _read_usage(message: dict) -> dict | None:
    """Pull the four cost-relevant fields out of a message's `usage` block."""
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        "input": usage.get("input_tokens", 0) or 0,
        "cache_write": usage.get("cache_creation_input_tokens", 0) or 0,
        "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
        "output": usage.get("output_tokens", 0) or 0,
    }


def _merge_usage_max(a: dict, b: dict) -> dict:
    """Element-wise max of two usage snapshots for the same message.id.

    Claude Code splits one assistant message into several JSONL lines (one
    per content block), and every line for that message.id repeats the
    message-level usage. In the common case all repeats are byte-identical.
    But streaming can also emit leading placeholder lines with all-zero
    usage (written before usage is known) or partial output_token counts
    that grow across lines before settling on the final value (both observed
    on real local transcripts). Element-wise max across every line seen for
    an id is correct for all three shapes: identical duplicates collapse to
    the same value, placeholder zeros are dominated by the real value once
    it appears, and a growing output_tokens count resolves to its final
    (largest) value regardless of which line it lands on.
    """
    return {key: max(a[key], b[key]) for key in USAGE_KEYS}


def _mentions_harnessloop(content) -> bool:
    return ".harnessloop" in json.dumps(content, ensure_ascii=False)


def _load_file_state(raw) -> tuple[int, str | None, dict, bool]:
    """Normalize one file's marker entry to (offset, pending_id, pending_usage, pending_attributed).

    Supports both the legacy schema (a bare int offset, pre-dedup-fix, with
    no carried-over message) and the current schema (a dict carrying the
    offset plus whatever message was still open — not yet billed — at that
    offset), so marker files written before this fix keep working; they just
    start with no pending message, which is always safe (see `settle()`).
    """
    if isinstance(raw, int) and not isinstance(raw, bool):
        return (raw if raw >= 0 else 0), None, _zero_usage(), False
    if isinstance(raw, dict):
        offset = raw.get("offset", 0)
        if not isinstance(offset, int) or offset < 0:
            offset = 0
        pending_id = raw.get("pending_id")
        if not isinstance(pending_id, str):
            pending_id = None
        pending_usage = raw.get("pending_usage")
        if not isinstance(pending_usage, dict) or not all(
            isinstance(pending_usage.get(key), int) for key in USAGE_KEYS
        ):
            pending_usage = _zero_usage()
        return offset, pending_id, pending_usage, bool(raw.get("pending_attributed", False))
    return 0, None, _zero_usage(), False


def settle(transcript_dir: Path, marker: dict) -> tuple[dict, dict]:
    """Aggregate usage after each file's marker offset; return (totals, new offsets).

    Dedup contract
    --------------
    A single assistant *message* is written as multiple JSONL lines (one per
    content block), each repeating that message's usage. Billing every line
    independently over-counts a message by however many lines it was split
    into — observed 2x-4x on real transcripts. This function instead groups
    consecutive lines by `message.id` and bills each id's usage exactly once,
    via `_merge_usage_max` across its lines.

    Cross-settlement-window boundary
    ---------------------------------
    This script is normally invoked *from inside* the very assistant message
    it is reporting on (the tool call is one content block of that message),
    so the marker offset routinely lands in the middle of a message's run of
    lines: earlier content-block lines for the in-progress message are
    already on disk; later ones (written after this tool call returns) are
    not yet. Naively deduping only within the current run's window would
    double-bill that message: once as a partial group now, again as a
    partial-or-full group next run.

    To prevent that, a message's usage is added to `totals` only once its
    group is known to be *closed* — i.e. once a line with a different
    (or absent) message.id is observed after it. The still-open group at
    end-of-file is carried forward in the returned offsets as
    `pending_id` / `pending_usage` / `pending_attributed` instead of being
    billed; the next run resumes merging into it before deciding whether to
    close and bill it. Net effect: every message.id is billed exactly once,
    by whichever run first sees a line for a different subsequent id. The
    trade-off is that the very last open message in a transcript (e.g. the
    one invoking this script) has its usage deferred to the next
    settlement rather than counted immediately — under-counting a handful
    of tokens at the tail is preferable to the multi-x over-counting this
    replaces. Lines without a message.id cannot be correlated at all and are
    billed on their own, matching pre-fix behavior for that case.
    """
    files_marker = marker.get("files", {}) if isinstance(marker.get("files"), dict) else {}
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
    new_offsets: dict[str, dict] = {}

    def bill(usage: dict, attributed: bool) -> None:
        totals["turns"] += 1
        totals["input"] += usage["input"]
        totals["cache_write"] += usage["cache_write"]
        totals["cache_read"] += usage["cache_read"]
        totals["output"] += usage["output"]
        if attributed:
            totals["protocol_turns"] += 1
            totals["protocol_output"] += usage["output"]

    for transcript in sorted(transcript_dir.glob("*.jsonl")):
        start, pending_id, pending_usage, pending_attributed = _load_file_state(
            files_marker.get(transcript.name)
        )
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
                usage = _read_usage(message)
                if usage is None:
                    continue
                mid = message.get("id")
                attributed = _mentions_harnessloop(message.get("content"))

                if mid is None:
                    # No id to correlate against: bill this line on its own
                    # (pre-fix behavior for this case). Does not touch
                    # whatever message is currently pending.
                    bill(usage, attributed)
                    continue

                if mid == pending_id:
                    # Another content-block line for the still-open message:
                    # fold it in, do not bill yet.
                    pending_usage = _merge_usage_max(pending_usage, usage)
                    pending_attributed = pending_attributed or attributed
                    continue

                # A different id: the previously pending message (if any) is
                # now known to be closed, so bill it, then open the new one.
                if pending_id is not None:
                    bill(pending_usage, pending_attributed)
                pending_id = mid
                pending_usage = usage
                pending_attributed = attributed

        # The group still open at end-of-file is NOT billed here — it may
        # gain more lines (and only then be known closed) next run. It is
        # carried forward instead. If the file shrank or was replaced (no
        # lines advance past `start`), any stale pending group loaded from
        # the marker is carried forward unchanged rather than dropped; it
        # will be billed once some future line with a different id appears.
        # That is safe: it is real, previously-unbilled usage, so billing it
        # exactly once later is correct.
        new_offsets[transcript.name] = {
            "offset": line_count,
            "pending_id": pending_id,
            "pending_usage": pending_usage,
            "pending_attributed": pending_attributed,
        }
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
                # version 2: "files" entries are dicts carrying an open
                # message.id (if any) across settlement windows, not bare
                # int offsets — see settle()'s dedup contract. load_json()
                # + _load_file_state() still accept version-1 (bare int)
                # marker files.
                {"version": 2, "updated": datetime.now().isoformat(timespec="seconds"), "files": new_offsets},
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
