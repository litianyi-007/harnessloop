# Harnessloop Evolution Issue

## Summary

- Issue ID: HLI-0001
- Issue class: validation-drift
- Status: open
- Source project: mock-project
- Created by: main session
- Created at: 2026-06-29

## Redaction Boundary

- Secrets removed: yes
- Private data removed: yes
- Raw logs omitted: no private logs exist
- Safe evidence summaries only: yes

## Context

- Active goal path: `.harnessloop/goals/20260629-001-runtime-quality/goal.md`
- Active round path: `.harnessloop/goals/20260629-001-runtime-quality/rounds/0001/`
- State files: `.harnessloop/state/current.md`, `.harnessloop/meta/self-audit.md`
- Related handoffs: `.harnessloop/goals/20260629-001-runtime-quality/rounds/0001/archive/0001-01-review-adversarial-closed.md`
- Related evidence: `.harnessloop/goals/20260629-001-runtime-quality/rounds/0001/evidence/runtime/test-output.md`
- Related reviews: `.harnessloop/goals/20260629-001-runtime-quality/rounds/0001/reviews/adversarial-review.md`

## Expected Harnessloop Behavior

The templates should make runtime validation thresholds explicit enough that review does not invent a stricter threshold after execution.

## Actual Harnessloop Behavior

The review relied on a runtime threshold that was implied by the goal but not written in `thresholds.md`.

## Minimal Reproduction From Files

1. Read `.harnessloop/goals/20260629-001-runtime-quality/thresholds.md`.
2. Observe that the runtime threshold is vague.
3. Read `.harnessloop/goals/20260629-001-runtime-quality/rounds/0001/reviews/adversarial-review.md`.
4. Observe that review requires explicit runtime behavior.

## Attempted Local Mitigation

- Evidence refresh: not needed.
- Scope narrowing: next action limited to `thresholds.md`.
- Contract revision: not needed because this is wording clarification.
- Handoff change: not needed.
- Rollback: not needed.
- Human confirmation: not required in sample control contract.

## Suggested Upstream Improvement

- Candidate target: template
- Proposed smallest change: add explicit validation-drift rows to self-audit and threshold templates.
- Why this generalizes beyond this project: runtime validation drift can happen in any project using local tests, remote automation, CI, probes, canaries, or monitoring.
- Risks of overfitting: avoid adding mock-project-specific runtime commands to the default template.

## Resolution

- Resolution status: not resolved
- Upstream change: none yet
- Backported to local policy: no
- Backport path:
- Follow-up required: analyze with `harness-loop-issue`
