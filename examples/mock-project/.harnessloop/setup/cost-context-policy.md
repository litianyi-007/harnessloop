# Cost And Context Policy

## Roles

- Main session: goal interpretation, scope approval, acceptance decision.
- Subagent/swarm: read-only investigation and adversarial review.

## Model Policy

- Codex: prefer subagent with `gpt-5.5` medium reasoning when available.
- Claude Code: prefer swarm or subagent with Sonnet high or extra-high reasoning when available.
- Other environments: use main-session model and effort unless delegation is verified.

## Context Policy

- Keep raw logs in evidence files.
- Bring only summaries and file paths into the main session.
- Do not delegate final acceptance after a failed review.

