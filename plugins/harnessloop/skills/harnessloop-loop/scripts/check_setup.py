#!/usr/bin/env python3
"""Machine-readable setup completeness checker for the Harnessloop protocol.

Reads the 5 setup/state files a fresh `init_project.py` run creates and
reports, per file, whether every field/table slot the templates define has
been filled in (see design-v2 section 4 for the full algorithm this
implements: `.harnessloop/goals/20260716-001-setup-wizard/rounds/0002/
evidence/dynamic/setup-wizard-design-v2.md`).

Placement rationale (design-v2 section 4.1): this script lives in
`harnessloop-loop/scripts/` alongside `init_project.py` and
`verify_protocol.py` rather than in `harnessloop-setup/scripts/`, so it can
reuse `init_project.BASE_FILES` (the single source of truth for the
file-to-template mapping) and `init_project.read_template()` (fenced
code-block extraction) via a same-directory import, and so the existing
"multiple skills read loop/scripts" convention is not inverted.

Same-directory import mechanism (design-v2 section 4.6, S9): when this file
is executed directly (`python3 check_setup.py ...`), Python puts the
script's own directory at `sys.path[0]`, so `import init_project` resolves
without any manual `sys.path` surgery. When this module is imported from
elsewhere (e.g. `harnessloop/scripts/validate.py`), the importer is
responsible for inserting this directory into `sys.path` first -- exactly
the existing precedent at `validate.py:32-34`
(`sys.path.insert(0, str(LOOP_SCRIPTS)); import init_project; import
verify_protocol`), which this module becomes a third entry in.

Zero-write guarantee (design-v2 section 4.6, S6): this script never writes
any project file (it is pure read/report). The only incidental write risk is
a `.pyc` bytecode cache for its own `import init_project` when invoked from
an environment that would otherwise cache imports; `sys.dont_write_bytecode
= True` below neutralizes that, and callers (status/continue/loop SKILL.md)
additionally invoke this script with `python3 -B` / `PYTHONDONTWRITEBYTECODE
=1` as a second, redundant guarantee.

Deviation from design-v2 section 4.4 (documented, sanctioned by the round
0003 handoff): design-v2 specifies a single `todo_count` field that would
need a de-duplication predicate between per-field literal `TODO (owner:
user)` values and `state/self-check.md`'s `Action` field TODO entries. The
adversarial review (round 0002, Finding 4) flagged that predicate as
undefined and offered two options; the round 0003-02 handoff adopts option
(ii): emit `field_todo_count` (leaf fields whose value is the literal `TODO
(owner: user)` marker, optionally followed by free text) and
`selfcheck_todo_count` (count of `TODO (owner: user):`-formatted entries
inside self-check.md's `Action` field) as two separate, never-merged
counters. Neither counter participates in `gate_blocking` or `complete`.

Exit codes (design-v2 section 4.5, unchanged by the above): 0 = complete
(5/5 files fully filled); 1 = incomplete; 2 = usage/environment error
(project path missing/not a directory, references/ missing, or a target
template file missing -- packaging problems, not "incomplete").
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.dont_write_bytecode = True

SKILL_DIR = Path(__file__).resolve().parents[1]
REFERENCES_DIR = SKILL_DIR / "references"

import init_project  # noqa: E402  (see module docstring: same-directory import)

TODO_LITERAL = "TODO (owner: user)"

# Order mirrors the wizard's S1-S5 steps; also the iteration/JSON key order
# and the `next_step` search order.
FILES_ORDER: List[str] = [
    ".harnessloop/state/environment.md",
    ".harnessloop/setup/data-sources.md",
    ".harnessloop/setup/cost-context-policy.md",
    ".harnessloop/state/control-contract.md",
    ".harnessloop/state/self-check.md",
]

# Each leaf-field tuple is (heading, container, label); heading/container may
# be None (self-check.md has no `##` headings at all -- section 4.2: "12
# fields degrade to a single-segment path"). Tables are listed by their own
# `##` heading name (section 4.2: table path = the heading itself).
MANIFEST = {
    ".harnessloop/state/environment.md": {
        "fields": [
            ("Detection", None, "Detected environment"),
            ("Detection", None, "Detected from"),
            ("Detection", None, "Available tools"),
            ("Detection", None, "Unavailable tools"),
            ("Delegation", None, "Expected mechanism"),
            ("Delegation", None, "Observed mechanism"),
            ("Delegation", None, "Can create independent task"),
            ("Delegation", None, "Can constrain read/write scope"),
            ("Delegation", None, "Can require output path"),
            ("Delegation", None, "Can verify evidence citations"),
            ("Model And Effort", None, "Expected model"),
            ("Model And Effort", None, "Observed model"),
            ("Model And Effort", None, "Expected effort/reasoning"),
            ("Model And Effort", None, "Observed effort/reasoning"),
            ("Model And Effort", None, "Verification method"),
            ("Model And Effort", None, "Mismatch action"),
            ("Model And Effort", None, "Residual risk"),
            ("Result", None, "Pass/fail"),
            ("Result", None, "Allowed next actions"),
            ("Result", None, "Required human action"),
            ("Result", None, "Last checked"),
        ],
        "tables": [],
    },
    ".harnessloop/setup/data-sources.md": {
        "fields": [],
        "tables": [
            "Static Sources",
            "Dynamic Or Generated Sources",
            "Runtime Validation Systems",
            "External Tools And Platforms",
            # Local Channel Parameters excluded: owned by $harnessloop-secrets
            # (design-v2 section 4.2 ownership-exemption table), not a wizard
            # slot even though its raw template row count is also 0.
        ],
    },
    ".harnessloop/setup/cost-context-policy.md": {
        "fields": [
            ("Main Session", "Responsibilities", "Orchestration"),
            ("Main Session", "Responsibilities", "Core decisions"),
            ("Main Session", "Responsibilities", "Final acceptance"),
            ("Main Session", "Must not spend context on", "Large raw logs"),
            ("Main Session", "Must not spend context on", "Full external reports"),
            ("Main Session", "Must not spend context on", "Repeated source dumps"),
            ("Delegation Rules", "Use subagent or swarm for", "Read-only discovery"),
            ("Delegation Rules", "Use subagent or swarm for", "Evidence collection"),
            ("Delegation Rules", "Use subagent or swarm for", "Low-context execution"),
            ("Delegation Rules", "Use subagent or swarm for", "Adversarial review"),
            ("Delegation Rules", "Use subagent or swarm for", "Acceptance testing"),
            ("Delegation Rules", "Do not delegate", "Goal interpretation"),
            ("Delegation Rules", "Do not delegate", "Goal breakdown approval"),
            ("Delegation Rules", "Do not delegate", "Scope-lock changes"),
            ("Delegation Rules", "Do not delegate", "Human-required product or business decisions"),
            ("Delegation Rules", "Do not delegate", "Acceptance after failed review"),
            ("Model Policy", "Codex", "Independent investigation"),
            ("Model Policy", "Codex", "Low-context execution"),
            ("Model Policy", "Codex", "Adversarial review"),
            ("Model Policy", "Codex", "Core decisions"),
            ("Model Policy", "Claude Code", "Independent investigation"),
            ("Model Policy", "Claude Code", "Low-context execution"),
            ("Model Policy", "Claude Code", "Adversarial review"),
            ("Model Policy", "Claude Code", "Core decisions"),
            ("Handoff Budget Rules", None, "Input limit"),
            ("Handoff Budget Rules", None, "Output limit"),
            ("Handoff Budget Rules", None, "Evidence path requirement"),
            ("Handoff Budget Rules", None, "Summary requirement"),
            ("Handoff Budget Rules", None, "Context that must stay out of main session"),
        ],
        "tables": [],
    },
    ".harnessloop/state/control-contract.md": {
        "fields": [
            ("Auto-Continue", "Allowed when", "Feedback class"),
            ("Auto-Continue", "Allowed when", "Evidence health"),
            ("Auto-Continue", "Allowed when", "Environment self-check"),
            ("Auto-Continue", "Allowed when", "Open handoffs"),
            ("Auto-Continue", "Allowed when", "Human confirmation"),
            ("Human Confirmation Required", "Required for", "Scope-lock mutation"),
            ("Human Confirmation Required", "Required for", "Evidence contract revision"),
            ("Human Confirmation Required", "Required for", "Control contract revision"),
            ("Human Confirmation Required", "Required for", "Failed review acceptance"),
            ("Human Confirmation Required", "Required for", "Rollback"),
            ("Human Confirmation Required", "Required for", "Irreversible or external-system write"),
            ("Stop Conditions", "Stop when", "Blocking condition"),
            ("Stop Conditions", "Stop when", "Blocker type"),
            ("Stop Conditions", "Stop when", "Missing evidence"),
            ("Stop Conditions", "Stop when", "Environment mismatch"),
            ("Stop Conditions", "Stop when", "Model/effort mismatch"),
            ("Stop Conditions", "Stop when", "Contract cannot be evaluated"),
            ("Delegation Boundaries", None, "Allowed delegated work"),
            ("Delegation Boundaries", None, "Disallowed delegated work"),
            ("Delegation Boundaries", None, "Required handoff evidence"),
            ("Acceptance Authority", None, "Round acceptance"),
            ("Acceptance Authority", None, "Failed review escalation"),
            ("Acceptance Authority", None, "Blocked state unblock requirement"),
            ("Acceptance Authority", None, "Recoverable blocker auto-round policy"),
        ],
        "tables": [],
    },
    ".harnessloop/state/self-check.md": {
        "fields": [
            (None, None, "Setup files present"),
            (None, None, "Environment policy recorded"),
            (None, None, "Control contract recorded"),
            (None, None, "Evidence index recorded"),
            (None, None, "Self-audit present"),
            (None, None, "Runtime validation described"),
            (None, None, "Data/tool access described"),
            (None, None, "Local channel parameter store protected"),
            (None, None, "Delegation model verified"),
            (None, None, "Intake gate required"),
            (None, None, "Action"),
            (None, None, "Last checked"),
        ],
        "tables": [],
    },
}

# design-v2 section 4.4 (M1): gate_blocking is true iff any of these three
# core policy files is `template` or `missing`. data-sources.md and
# self-check.md deliberately excluded (section 3, section 4.4, and the
# adversarial review Finding 3 both explain why: excluding them is a
# necessary condition for AC3/AC6, not a laxity).
GATE_BLOCKING_FILES = frozenset(
    {
        ".harnessloop/state/environment.md",
        ".harnessloop/state/control-contract.md",
        ".harnessloop/setup/cost-context-policy.md",
    }
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _label_pattern(label: str) -> re.Pattern:
    """Tolerant leaf-field label matcher (section 4.3 + S10 + R4).

    Tolerates a leading `#`/`-`/`*`/whitespace run, the label wrapped in
    `**bold**`, extra whitespace around the colon, and -- the R4 fix -- a
    closing `**` sitting *after* the colon as in `**Label:** value` (where
    the colon is inside the bold span). Without the `\\**` right after the
    literal colon, that form would leak the closing `**` into the captured
    value, making an empty `**Label:**` field look non-blank.
    """
    return re.compile(
        r"^[#\-*\s]*\**\s*" + re.escape(label) + r"\s*\**\s*:\s*\**\s*(.*)$"
    )


def _container_pattern(container: str) -> re.Pattern:
    """Container-line matcher: same tolerances as a leaf label, but the line
    must end right after the colon (nothing but optional bold/space), since
    a container is followed by a sub-list rather than an inline value."""
    return re.compile(
        r"^[#\-*\s]*\**\s*" + re.escape(container) + r"\s*\**\s*:\s*\**\s*$"
    )


def _clean_value(raw: str) -> str:
    value = raw.strip()
    value = re.sub(r"^\*+", "", value).strip()
    return value


def _find_heading_slice(lines: List[str], heading: str) -> Optional[Tuple[int, int]]:
    """Return the (start, end) line-index range of the content strictly
    under `## heading`, up to the next heading of equal-or-higher level or
    end of file (section 4.3 step 1)."""
    start_idx = None
    start_level = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and m.group(2) == heading:
            start_idx = i
            start_level = len(m.group(1))
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        m = _HEADING_RE.match(lines[j])
        if m and len(m.group(1)) <= start_level:
            end_idx = j
            break
    return start_idx + 1, end_idx


def _find_container_slice(
    lines: List[str], start: int, end: int, container: str, other_containers: List[str]
) -> Optional[Tuple[int, int]]:
    """Return the (start, end) line-index range of the content under the
    named container line, bounded by the next sibling container line (from
    `other_containers`) or the enclosing slice end (section 4.3 step 2)."""
    cont_re = _container_pattern(container)
    c_start = None
    for i in range(start, end):
        if cont_re.match(lines[i]):
            c_start = i
            break
    if c_start is None:
        return None
    other_res = [_container_pattern(c) for c in other_containers if c != container]
    c_end = end
    for j in range(c_start + 1, end):
        if any(r.match(lines[j]) for r in other_res):
            c_end = j
            break
    return c_start + 1, c_end


def _containers_by_heading(fields: List[tuple]) -> dict:
    result: dict = {}
    for heading, container, _label in fields:
        if heading and container:
            result.setdefault(heading, [])
            if container not in result[heading]:
                result[heading].append(container)
    return result


def locate_field_line(
    text: str, rel: str, heading: Optional[str], container: Optional[str], label: str
) -> Optional[int]:
    """Return the 0-based line index of a leaf field's label line within
    `text` (the contents of manifest file `rel`), honoring the same
    heading/container slicing detection uses. Exposed (not internal-only) so
    `validate.py`'s programmatic fixture construction (design-v2 section
    7.2) can locate the exact line to fill without re-implementing the
    section 4.3 slicing algorithm, keeping fixture generation and detection
    from drifting apart. `rel` disambiguates which file's manifest entry
    owns `(heading, container)` -- heading names happen to be unique across
    the 5 files today, but taking `rel` explicitly avoids relying on that.
    """
    lines = text.splitlines()
    if heading:
        hs = _find_heading_slice(lines, heading)
        if hs is None:
            return None
        start, end = hs
    else:
        start, end = 0, len(lines)

    if container:
        other_containers = _containers_by_heading(MANIFEST[rel]["fields"]).get(heading, [])
        cs = _find_container_slice(lines, start, end, container, other_containers)
        if cs is None:
            return None
        start, end = cs

    label_re = _label_pattern(label)
    for i in range(start, end):
        if label_re.match(lines[i]):
            return i
    return None


def render_leaf_value(line: str, label: str, value: str) -> str:
    """Return `line` with its captured value replaced by `value`, keeping
    any leading markdown decoration (list dash, bold markers, indentation)
    intact. Paired with `locate_field_line` for fixture construction."""
    m = _label_pattern(label).match(line)
    if not m:
        raise ValueError(f"label {label!r} does not match line {line!r}")
    return line[: m.start(1)] + value


def render_sentinel_line(heading: str) -> str:
    """Build the canonical S1-tightened 'none declared' sentinel line for a
    table slot under `## heading` (section 3's wizard wording, section 4.3's
    matching regex): the category name is the heading's own lowercase
    form."""
    return f"_No {heading.lower()} declared for this project (confirmed via setup wizard)._"


def _sentinel_pattern(heading: str) -> re.Pattern:
    """Build the heading-bound 'none declared' sentinel matcher (hopper
    T-001 review Finding 2 / TH-0009 fix).

    Previously a single module-level `_SENTINEL_RE` accepted any line of the
    shape `No/None ... (confirmed via setup wizard).` regardless of which
    table heading it appeared under, so a syntactically valid sentinel
    written for the *wrong* category (e.g. the "Dynamic Or Generated
    Sources" sentinel pasted under "Static Sources") was accepted as if it
    answered the table it was actually found in. This binds the match to
    `render_sentinel_line(heading)`'s own canonical text for *this* heading:
    the category segment (`heading.lower()`) and everything else in the
    sentence must match verbatim. The only tolerances kept from the old
    regex are the ones S1 explicitly allows: an optional leading/trailing
    `_` (markdown italics may or may not be present) and case-insensitivity
    of the leading `No`/`None` word.
    """
    canonical = render_sentinel_line(heading).strip("_")
    if not canonical.lower().startswith("no "):
        # render_sentinel_line always starts with "No "; guard rather than
        # silently building a pattern that can never match anything.
        raise AssertionError(f"unexpected sentinel shape for heading {heading!r}: {canonical!r}")
    rest = canonical[len("No "):]
    return re.compile(r"^_?\s*(?:(?i:no|none))\s+" + re.escape(rest) + r"\s*_?\s*$")


def locate_table_bounds(text: str, heading: str) -> Optional[Tuple[int, int]]:
    """Return (separator_line_index, slice_end_index) for the table under
    `## heading`, or None if the heading/separator cannot be found. Exposed
    for the same fixture-construction reuse reason as `locate_field_line`."""
    lines = text.splitlines()
    hs = _find_heading_slice(lines, heading)
    if hs is None:
        return None
    start, end = hs
    for i in range(start, end):
        if _is_separator_row(lines[i]):
            return i, end
    return None


def _is_separator_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "-" not in stripped:
        return False
    return bool(re.match(r"^[|:\-\s]+$", stripped))


def _resolve_leaf(
    text: str, heading: Optional[str], container: Optional[str], label: str, other_containers: List[str]
) -> Optional[str]:
    lines = text.splitlines()
    if heading:
        hs = _find_heading_slice(lines, heading)
        if hs is None:
            return None
        start, end = hs
    else:
        start, end = 0, len(lines)

    if container:
        cs = _find_container_slice(lines, start, end, container, other_containers)
        if cs is None:
            return None
        start, end = cs

    label_re = _label_pattern(label)
    for i in range(start, end):
        m = label_re.match(lines[i])
        if m:
            return _clean_value(m.group(1))
    return None


def _resolve_table(text: str, heading: str) -> Tuple[bool, bool]:
    """Return (has_data_rows, has_sentinel) for the table under `## heading`."""
    lines = text.splitlines()
    hs = _find_heading_slice(lines, heading)
    if hs is None:
        return False, False
    start, end = hs

    sep_idx = None
    for i in range(start, end):
        if _is_separator_row(lines[i]):
            sep_idx = i
            break

    has_rows = False
    if sep_idx is not None:
        for j in range(sep_idx + 1, end):
            # A real table row starts with `|`; a stray prose line (e.g. "not
            # sure yet...") left in an otherwise-empty table section must not
            # count as "answered" (M-B fix: the previous `lines[j].strip()`
            # truthiness check treated any non-blank line as a data row,
            # bypassing the S1 sentinel anchor -- prose neither matches the
            # sentinel regex nor is a genuine row, so it must not satisfy
            # either path to "filled").
            stripped = lines[j].strip()
            if not stripped.startswith("|"):
                continue
            # hopper T-001 review Finding 1 / TH-0009 fix: a row of all-empty
            # cells (e.g. `|  |  |`, the raw template row shape) must not
            # count as data either -- only a row with at least one non-blank
            # cell (after stripping) is a genuine answered row. Previously
            # `startswith("|")` alone was sufficient, so the template's own
            # empty separator-following row satisfied "filled".
            cells = stripped.strip("|").split("|")
            if any(cell.strip() for cell in cells):
                has_rows = True
                break

    has_sentinel = any(_sentinel_pattern(heading).match(lines[i]) for i in range(start, end))
    return has_rows, has_sentinel


def _path_string(heading: Optional[str], container: Optional[str], label: str) -> str:
    parts = [p for p in (heading, container, label) if p]
    return " > ".join(parts)


def _template_name_for(rel: str) -> str:
    return init_project.BASE_FILES[rel]


def _file_report(project: Path, rel: str) -> dict:
    spec = MANIFEST[rel]
    total = len(spec["fields"]) + len(spec["tables"])
    path = project / rel

    if not path.exists():
        missing_sections = [_path_string(h, c, l) for h, c, l in spec["fields"]] + list(
            spec["tables"]
        )
        return {
            "state": "missing",
            "missing_sections": missing_sections,
            "fields_filled": 0,
            "fields_total": total,
            "field_todo": 0,
        }

    text = path.read_text(encoding="utf-8")
    template_text = init_project.read_template(_template_name_for(rel))
    containers_by_heading = _containers_by_heading(spec["fields"])

    missing_sections: List[str] = []
    filled_count = 0
    field_todo = 0

    for heading, container, label in spec["fields"]:
        other = containers_by_heading.get(heading, []) if heading else []
        resolved = _resolve_leaf(text, heading, container, label, other)
        template_value = _resolve_leaf(template_text, heading, container, label, other)
        if template_value is None:
            template_value = ""

        if resolved is None:
            filled = False
        else:
            filled = not (resolved == "" or resolved == template_value)
            if filled and resolved.startswith(TODO_LITERAL):
                field_todo += 1

        if filled:
            filled_count += 1
        else:
            missing_sections.append(_path_string(heading, container, label))

    for heading in spec["tables"]:
        has_rows, has_sentinel = _resolve_table(text, heading)
        if has_rows or has_sentinel:
            filled_count += 1
        else:
            missing_sections.append(heading)

    if filled_count == 0:
        state = "template"
    elif filled_count == total:
        state = "filled"
    else:
        state = "partial"

    return {
        "state": state,
        "missing_sections": missing_sections,
        "fields_filled": filled_count,
        "fields_total": total,
        "field_todo": field_todo,
    }


def _count_selfcheck_todos(project: Path) -> int:
    """Count `TODO (owner: user):`-formatted entries inside self-check.md's
    `Action` field (see module docstring re: field_todo_count vs
    selfcheck_todo_count -- these are deliberately never merged)."""
    path = project / ".harnessloop/state/self-check.md"
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    action_re = _label_pattern("Action")
    last_checked_re = _label_pattern("Last checked")

    start = None
    for i, line in enumerate(lines):
        if action_re.match(line):
            start = i
            break
    if start is None:
        return 0

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if last_checked_re.match(lines[j]):
            end = j
            break

    block = "\n".join(lines[start:end])
    return len(re.findall(re.escape(TODO_LITERAL) + r"\s*:", block))


def build_report(project: Path) -> dict:
    files_report: "dict[str, dict]" = {}
    complete = True
    filled_files = 0
    gate_blocking = False
    field_todo_total = 0

    for rel in FILES_ORDER:
        fr = _file_report(project, rel)
        field_todo_total += fr.pop("field_todo")
        files_report[rel] = fr
        if fr["state"] == "filled":
            filled_files += 1
        else:
            complete = False
        if rel in GATE_BLOCKING_FILES and fr["state"] in ("template", "missing"):
            gate_blocking = True

    selfcheck_todo_count = _count_selfcheck_todos(project)

    next_step = None
    for rel in FILES_ORDER:
        if files_report[rel]["state"] != "filled":
            next_step = rel
            break

    return {
        "project": str(project),
        "files": files_report,
        "complete": complete,
        "filled": filled_files,
        "total": len(FILES_ORDER),
        "gate_blocking": gate_blocking,
        "field_todo_count": field_todo_total,
        "selfcheck_todo_count": selfcheck_todo_count,
        "next_step": next_step,
    }


def _print_human(report: dict) -> None:
    print(f"Harnessloop setup check: {report['project']}")
    for rel in FILES_ORDER:
        fr = report["files"][rel]
        display = rel.removeprefix(".harnessloop/")
        line = f"  {display}: {fr['state']} ({fr['fields_filled']}/{fr['fields_total']})"
        if fr["missing_sections"]:
            line += " — missing: " + ", ".join(fr["missing_sections"])
        print(line)

    print(f"Setup completeness: {report['filled']}/{report['total']} files fully filled.")

    if report["gate_blocking"]:
        blocking_file = None
        for rel in FILES_ORDER:
            if rel in GATE_BLOCKING_FILES and report["files"][rel]["state"] in ("template", "missing"):
                blocking_file = rel
                break
        display = blocking_file.removeprefix(".harnessloop/") if blocking_file else "unknown"
        print(f"Setup gate: BLOCKING — {display} is still {report['files'][blocking_file]['state']}.")
    elif not report["complete"]:
        print(f"Setup gate: WARNING — {report['total'] - report['filled']} file(s) incomplete (non-blocking).")
    else:
        print("Setup gate: COMPLETE.")

    print(
        f"TODO count: field={report['field_todo_count']}, "
        f"self-check={report['selfcheck_todo_count']}"
    )

    if report["next_step"]:
        display = report["next_step"].removeprefix(".harnessloop/")
        print(f"Next setup step: {display} (run $harnessloop-setup)")
    else:
        print("Next setup step: none (setup complete)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report machine-readable Harnessloop setup completeness."
    )
    parser.add_argument("--project", "-p", default=".", help="Target project directory.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args()

    project = Path(args.project)
    if not project.exists() or not project.is_dir():
        print(f"error: project path does not exist or is not a directory: {project}", file=sys.stderr)
        return 2

    if not REFERENCES_DIR.exists():
        print(f"error: references directory not found: {REFERENCES_DIR}", file=sys.stderr)
        return 2

    project = project.resolve()

    try:
        report = build_report(project)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_human(report)

    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
