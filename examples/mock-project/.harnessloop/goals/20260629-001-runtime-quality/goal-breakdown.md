# Goal Breakdown

## Long-Term Goal

Improve generated order summary reliability across runtime validation.

## Read-Only Discovery Plan

- Inspect current tests.
- Inspect fixture schema.
- Identify runtime validation output.

## Discovery Handoffs

| Handoff | Purpose | Inputs | Output path | Status |
| --- | --- | --- | --- | --- |
| none | sample keeps discovery inline | sample docs | n/a | n/a |

## Subgoals

| ID | Subgoal | Depends on | Evidence required | Validation method | Risk |
| --- | --- | --- | --- | --- | --- |
| SG-1 | Confirm runtime validation behavior | none | runtime test output | local test output cited by review | validation drift |

## Tasks

| ID | Task | Parent subgoal | Scope boundary | Evidence required | Validation method |
| --- | --- | --- | --- | --- | --- |
| T-1 | Run and review local runtime test | SG-1 | no source changes | runtime evidence and review | adversarial review |

## Main-Session Decision

Chosen sequence: execute T-1 first, then repair thresholds if review identifies validation drift.

Rejected alternatives: changing source before runtime evidence.

Reasoning: runtime evidence is required before deciding whether code or contract changes are needed.

