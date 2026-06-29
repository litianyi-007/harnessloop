# Harnessloop

![Harnessloop evidence cycle](docs/assets/harnessloop-hero-evidence-cycle.png)

Harnessloop is a project-local protocol and plugin for long-running AI agent work. It keeps goals, evidence, handoffs, validation, session takeover, and self-audit in files so a task can continue across agents without losing context or accepting unsupported claims.

Use it when the task is too important or too long to trust chat memory alone.

## Why

Long agent sessions fail in predictable ways:

- Context gets compressed or lost.
- Work continues without fresh evidence.
- One session cannot safely hand off to another.
- Runtime validation drifts from the goal.
- External tools, accounts, and data sources are implicit.
- Reviews become generic engineering opinions instead of evidence-backed gates.

Harnessloop turns that work into an explicit loop:

![Harnessloop five gates](docs/assets/harnessloop-overview-five-gates.svg)

## When To Use

Use Harnessloop for:

- Long coding, research, data, or validation tasks.
- Work that depends on real static data, generated data, runtime evidence, source code, or external systems.
- Cross-session task takeover from another agent.
- Tasks that need minimal-change scope locks and auditable handoffs.
- Work where failure, rollback, or human confirmation must be explicit.

Do not use it for:

- One-off questions.
- Small edits that can be verified immediately.
- Tasks where no durable evidence or handoff is needed.

## Install

Codex on Windows:

```powershell
.\scripts\install-codex.ps1
```

Claude Code on Windows:

```powershell
.\scripts\install-claude.ps1
```

Codex on macOS/Linux:

```bash
./scripts/install-codex.sh
```

Claude Code on macOS/Linux:

```bash
./scripts/install-claude.sh
```

Equivalent CLI commands:

```powershell
codex plugin marketplace add .
codex plugin add harnessloop@harnessloop

claude plugin marketplace add . --scope user
claude plugin install harnessloop@harnessloop --scope user
```

## Start Your First Loop

Harnessloop is currently a skill/protocol, not a standalone shell CLI. Explicit Codex skill invocation uses kebab-case names such as `$harnessloop-init`; colon forms such as `harnessloop:init` are natural-language aliases only. `$harnessloop:init` is not a valid skill mention.

After installing, ask the agent:

```text
$harnessloop-init
```

For deterministic initialization from this repository:

```powershell
.\scripts\init-project.ps1 -Project C:\path\to\target-project
```

macOS/Linux:

```bash
./scripts/init-project.sh --project /path/to/target-project
```

The first setup creates or fills:

```text
.harnessloop/
  setup/
    data-sources.md
    cost-context-policy.md
  local/
    .gitignore
    channel-params.example.json
  state/
    current.md
    environment.md
    control-contract.md
    evidence-index.md
    self-check.md
  meta/
    self-audit.md
    evolution-issues/
  goals/
```

Then use `$harnessloop-loop` to define a goal, create decomposable thresholds, lock the first round scope, write evidence, run adversarial review, classify feedback, and continue only through the control gate.

If a runtime blocker appears, Harnessloop classifies it before stopping. Recoverable blockers move into a bounded read-only investigation round; missing access, unsafe writes, external triggers, cleanup decisions, or business decisions pause and ask the user for the exact missing input.

## Take Over An Existing Agent Session

The source session does not need Harnessloop installed. Ask it to generate a `Harnessloop Transfer Packet`, then save the result:

```powershell
.\scripts\init-project.ps1 -Project C:\path\to\target-project -Intake task-slug
```

```text
.harnessloop/intake/YYYYMMDD-HHMM-<task-slug>/transfer-packet.md
```

Harnessloop runs an intake gate before creating a formal goal:

```text
$harnessloop-intake
```

![Harnessloop takeover intake flow](docs/assets/takeover-intake-flow.svg)

If the packet is incomplete, Harnessloop writes `gap-review.md` and asks only for missing facts. If it passes, the first round should normally be `intake-review`, which maps imported evidence into `.harnessloop/state/evidence-index.md` before any business execution continues.

The transfer packet must include task identity, goal contract, progress state, change state, documentation inventory, process artifacts, evidence, external tools, credential requirements without secret values, local channel parameter keys, decisions, risks, and next handoff recommendation. See [docs/usage.md](docs/usage.md) for the full prompt.

## Evidence Model

Harnessloop separates evidence artifact health from whether that evidence supports acceptance. A failed runtime test can be a valid evidence artifact and still produce negative feedback.

![Harnessloop evidence stack](docs/assets/evidence-stack.svg)

Evidence classes:

- `static`: real datasets, docs, reports, source-of-truth records.
- `dynamic`: generated data, sampled outputs, model/tool outputs.
- `runtime`: tests, CI, remote automation, probes, canaries, monitoring.
- `source`: repository source, schema files, source-data files.

## External Channels

Harnessloop separates channel inventory from connectivity checks:

- `$harnessloop-channels`: lists declared external systems, tools, MCP servers, CLIs, APIs, CI systems, databases, brokers, and credential references without probing.
- `$harnessloop-connectivity`: runs only declared connectivity methods after the required tool, endpoint/resource, credential reference, permission scope, parameters, and write-safety rules are explicit.
- `$harnessloop-secrets`: creates and checks local-only channel parameter keys in `.harnessloop/local/channel-params.json`; values are never committed or copied into evidence.

If a channel self-check fails, is blocked, is skipped, or needs user confirmation because information is missing, Harnessloop must ask for the exact missing facts before trying alternatives or continuing.

## Key Concepts

- `goal`: what the loop is trying to achieve.
- `transfer packet`: a structured handoff from an existing agent session.
- `intake gate`: the takeover review that blocks unsafe continuation.
- `scope-lock`: the exact boundary of what one round may change.
- `evidence gate`: proof required before a round can pass.
- `handoff`: a file-based task transfer for subagents or reviewers.
- `channel inventory`: declared external systems and tools, listed without probing.
- `connectivity check`: declared access verification that stops and asks when required access facts are missing.
- `local channel parameters`: ignored local values or provider references used by external channels.
- `blocker type`: classification that decides whether a blocked round can continue into read-only recovery or must ask the user.
- `self-audit`: loop health check for dead loops, contradictions, drift, and runaway context.
- `evolution issue`: a redacted issue that helps improve Harnessloop itself.

## Execution Delegation

Harnessloop keeps the main session responsible for orchestration and control decisions. It delegates bounded work through file handoffs when doing so protects context and improves review quality:

| Task type | Decision |
| --- | --- |
| Read-only discovery | Should delegate when paths and questions are bounded. |
| Evidence collection | Delegate only when read-only, sensitivity is understood, and outputs cite paths. |
| External connectivity | Use `$harnessloop-connectivity`; do not delegate blind probing. |
| Low-risk local implementation | May delegate with scope-lock, rollback, and verification commands. |
| High-risk implementation | Main session owns integration; delegate only narrow subtasks. |
| Adversarial review and acceptance testing | Delegate when the mechanism and evidence citations are verifiable. |
| Round acceptance and control decisions | Never delegate. |

Run `$harnessloop-delegation` before relying on subagent or swarm work when model, effort, scope control, output path control, or evidence citation behavior must be verified.

## Skills

- `$harnessloop-init`: initialize `.harnessloop/` project files.
- `$harnessloop-intake`: review transfer packets and run intake gates.
- `$harnessloop-goal`: inspect, negotiate, update, split, archive, cancel, supersede, or assess deletion impact for goals.
- `$harnessloop-evidence`: add, check, revise, reject, or diff evidence contracts.
- `$harnessloop-channels`: list declared external systems, channels, and tools without probing.
- `$harnessloop-connectivity`: check declared external system/tool connectivity and ask for missing access facts.
- `$harnessloop-secrets`: manage local channel parameter keys, secret references, presence checks, and redaction rules.
- `$harnessloop-delegation`: check subagent/swarm readiness, scope control, output paths, evidence citation behavior, and model/effort match.
- `$harnessloop-status`: read current Harnessloop state.
- `$harnessloop-continue`: run continuation gates before execution.
- `$harnessloop-loop`: run or take over a goal-driven Harnessloop in an installed project.
- `$harnessloop-issue`: record, analyze, or propose fixes for Harnessloop evolution issues.

## Repository Map

- `docs/usage.md`: product-level usage guide and transfer packet prompt.
- `docs/harnessloop-framework.md`: framework design and detailed protocol.
- `docs/harnessloop-flow.mmd`: canonical detailed Mermaid flow source.
- `docs/harnessloop-flow.svg`: rendered detailed flow preview.
- `docs/assets/`: README and documentation visuals.
- `plugins/harnessloop/`: plugin source.
- `plugins/harnessloop/skills/`: installable skills and templates.
- `examples/mock-project/`: artificial reference project showing setup, intake, evidence, review, decision, self-audit, and evolution issue files.

## Validate

```powershell
.\scripts\validate.ps1
```

The validation script checks marketplace manifests and runs Claude Code strict validation against the marketplace root and plugin root.

Validate skills directly:

```powershell
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-init
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-loop
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-goal
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-evidence
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-channels
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-connectivity
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-secrets
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-delegation
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-status
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-continue
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-intake
python C:\Users\litianyi\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\harnessloop\skills\harnessloop-issue
```

## Current Limits

- Harnessloop defines a protocol and skills; it does not yet provide a full shell CLI.
- It does not ship fixed data connectors. Projects must declare their own tools, accounts, data sources, and validation systems.
- The detailed flow should be maintained from `docs/harnessloop-flow.mmd`; generated or decorative imagery must not replace evidence-bearing flow diagrams.

Keep the plugin name as `harnessloop` in both manifests so marketplace selectors stay stable:

```text
harnessloop@harnessloop
```
