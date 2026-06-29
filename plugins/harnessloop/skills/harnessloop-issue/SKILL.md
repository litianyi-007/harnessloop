---
name: harnessloop-issue
description: "Use when the user references harnessloop:issue or asks to record, analyze, or propose a fix for a Harnessloop evolution issue, framework question, protocol defect, self-audit concern, skill gap, template gap, packaging gap, or plugin behavior problem. This skill records user questions as evolution issues and analyzes them without copying project-private context."
---

# Harnessloop Issue

Use this skill when the input is a user question about Harnessloop itself, a request to record a Harnessloop concern, an issue report from `.harnessloop/meta/evolution-issues/`, or an equivalent Harnessloop self-audit report.

The goal is to improve Harnessloop itself. Do not solve the source project's business problem unless that is required to understand the Harnessloop failure.

## Input Contract

Accept an explicit skill invocation such as:

- `$harnessloop-issue record <question or concern>`
- `$harnessloop-issue analyze .harnessloop/meta/evolution-issues/0001-example.md`
- `$harnessloop-issue propose-fix .harnessloop/meta/evolution-issues/0001-example.md`

Treat `harnessloop:issue` as a natural-language alias only; `$harnessloop:issue` is not a valid skill invocation.

Supported actions:

- `record`: create or draft an evolution issue from a user question, concern, self-audit finding, unclear protocol behavior, missing skill behavior, template gap, packaging gap, or plugin problem.
- `analyze`: classify an existing issue and identify the smallest upstream improvement.
- `propose-fix`: produce the smallest upstream patch outline or apply it when the user explicitly asks for code changes.

For `record`, useful input includes:

- Summary of the question or suspected Harnessloop problem.
- Expected Harnessloop behavior.
- Actual or observed behavior.
- Scope: docs, template, main loop, issue skill, another skill, examples, validation script, plugin packaging, marketplace, or unknown.
- Project-local file paths or redacted excerpts, if available.
- Attempted local mitigation, if any.
- Whether the user wants a file written or only a draft.

For `analyze` or `propose-fix`, require the issue content to include:

- Summary and issue class.
- Redaction boundary.
- Expected Harnessloop behavior.
- Actual Harnessloop behavior.
- File paths or redacted excerpts for state, goal, round, evidence, handoff, review, or decision records.
- Attempted local mitigation.
- Suggested upstream improvement, if available.

If the report contains secrets, credentials, raw private data, customer data, or unnecessary source dumps, stop and ask for a redacted version or create a redaction plan before analyzing.

## Processing Contract

For `record`, create a concise evolution issue using `references/evolution-issue-template.md` from `$harnessloop-loop` when available. If `.harnessloop/` exists, write the issue under `.harnessloop/meta/evolution-issues/` using a stable filename such as `YYYYMMDD-NNN-<slug>.md`. If `.harnessloop/` is missing or the user asks for a draft only, return a draft issue and suggest `$harnessloop-init` before writing project-local state.

For `analyze` and `propose-fix`, read only the issue and cited Harnessloop files needed to reconstruct the protocol failure. Classify the failure, separate local-project causes from reusable framework gaps, and choose the smallest upstream target: docs, template, main skill, issue skill, example, validation script, or packaging metadata. Do not import broad project context.

When required fields are missing for `record`, ask focused questions only for the missing fields needed to write a useful issue. Do not invent expected behavior, actual behavior, project paths, mitigation history, or upstream target.

## Output Contract

For `record`, return the issue path or draft, issue class, redaction boundary, missing fields, and next action. For `analyze`, return a structured analysis with classification, evidence used, root protocol gap, recommended upstream change, smallest patch outline, overfitting risk, residual project action, and resolution/backport guidance. For `propose-fix`, return or apply the smallest patch only when the user explicitly asks for repository changes.

Do not modify upstream Harnessloop repository files unless the user asks for the proposed upstream patch.

## Record Workflow

1. Determine whether the user wants to record a question, concern, defect, or self-audit finding.
2. Redact secrets and private data before writing. Store summaries and file paths, not raw sensitive content.
3. Classify the issue as one of:
   - `dead-loop`
   - `contradiction`
   - `goal-drift`
   - `evidence-drift`
   - `validation-drift`
   - `handoff-stagnation`
   - `cost-context-runaway`
   - `documentation-gap`
   - `template-gap`
   - `skill-gap`
   - `packaging-gap`
4. If classification is uncertain, use `documentation-gap` for unclear user-facing behavior, `skill-gap` for missing agent instructions, or `packaging-gap` for install/visibility/invocation problems.
5. Write `.harnessloop/meta/evolution-issues/YYYYMMDD-NNN-<slug>.md` when project-local Harnessloop state exists and writing was requested or implied.
6. Include unresolved fields as `unknown` or `needs-user-confirmation`; ask the user immediately if the missing field affects redaction safety, expected behavior, actual behavior, or whether the issue may be written.

## Analysis Workflow

1. Classify the issue:
   - `local-project`: project data, code, or external system caused the failure.
   - `documentation-gap`: users lacked product-level guidance.
   - `template-gap`: a required field or state shape is missing.
   - `workflow-gap`: the protocol allowed an unsafe or ambiguous next action.
   - `skill-gap`: `harnessloop-loop` instructions were unclear, too broad, or missing.
   - `issue-skill-gap`: this issue-processing skill lacks needed guidance.
   - `packaging-gap`: marketplace, install, or plugin metadata created the problem.

2. Reconstruct the minimal failure path from file evidence:
   - Start from `state/current.md` or the issue's state summary.
   - Follow linked goal, round, handoff, evidence, review, and decision files.
   - Use summaries and cited paths; do not import broad raw context.

3. Decide whether the upstream Harnessloop framework should change:
   - If the issue is purely local, recommend no upstream change and explain the missing local repair.
   - If the issue generalizes, identify the smallest useful change.
   - Prefer docs or template changes before expanding skill behavior.
   - Update the main `harnessloop-loop` skill only when the agent execution protocol itself is unclear or unsafe.

4. Produce a concise proposal:
   - Classification.
   - Evidence used.
   - Root protocol gap.
   - Recommended target file type: docs, template, main skill, issue skill, example, validation script, or packaging metadata.
   - Smallest patch outline.
   - Overfitting risk.
   - Residual project-local action, if any.
   - Resolution or backport action when the issue has already been fixed upstream.

## Decision Rules

Do not turn one project's domain into a Harnessloop default. Keep external tools, data source types, runtime systems, and account requirements project-defined unless the failure is about how users describe or validate them.

Treat repeated neutral feedback as a loop failure when no new evidence, narrower scope, or contract repair appears.

Treat contradictions as framework issues only when Harnessloop templates or instructions made the contradiction easy to create or hard to detect.

Treat model/effort mismatch as packaging or environment-policy evidence only when the installed environment was expected to verify delegation and could not.

When an upstream change is accepted, state whether the installed project should backport it into local `.harnessloop/` policy, templates, or examples. Do not mark an issue closed until the expected resolution and local follow-up are explicit.

## Output Format

```markdown
# Harnessloop Issue Analysis

## Classification

## Evidence Used

## Root Protocol Gap

## Recommended Upstream Change

## Smallest Patch Outline

## Overfitting Risk

## Residual Project Action

## Resolution And Backport
```
