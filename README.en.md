# Harnessloop

**A protocol that makes a long-running AI agent task auditable — and is honest about what it cannot enforce.**

[![validate](https://github.com/litianyi-007/harnessloop/actions/workflows/validate.yml/badge.svg)](https://github.com/litianyi-007/harnessloop/actions/workflows/validate.yml)

> 🇨🇳 [中文](README.md) (default) ・ 🇯🇵 [日本語](README.ja.md)

## Why external validation sits outside the loop

After an agent finishes changing code, the thing that actually tells you whether the change
worked usually isn't in-process: it needs to be repackaged, deployed to a target environment,
brought up remotely, and the result lands on a separate data platform.

The standard agent loop handles this by **reading it as a log**. The agent glances at the
output, decides for itself whether to believe it, and moves on. The consequences:

- The verdict **can be ignored**, and the ignoring leaves no trace;
- The verdict **lives on the remote system** — once it's overwritten or rerun today, yesterday's
  round's conclusion can no longer be reproduced;
- When a round declares success, **nothing mechanical** can say "wait, your own record says fail."

This is the part Harnessloop handles.

## The core move: freeze the verdict into the round

It cuts work into **rounds**, and each round declares which paths it may change, what evidence
it will produce, and what verdict it reaches. An external system's verdict enters that round's
acceptance condition through a **round-local ledger**. Three moves have to stack together for
this to hold:

**① An eval is a first-class object with a stable ID.** `RAE-0001` is traceable across rounds,
not a one-off ad-hoc call.

**② The due set is frozen into the ledger at the moment it is written.** This step is the
hinge — it makes the verdict **purely round-local**, so whether a round should be accepted no
longer depends on whatever state the external system happens to be in today. Without this
step, any external verdict turns into a comparison across time layers, and that path lets
historical rounds drift with the remote system.

**③ The gate refuses "self-contradiction," not "a bad result."** It does not judge whether the
external system was right — it only refuses when your ledger says fail and your verdict says
positive.

> **In a standard loop, an external verdict is a sentence that can be ignored. Here, it is a
> record that can only be bypassed by an explicit override.**

## What a multi-stage pipeline looks like

Validating a heavyweight product (a client, an embedded target, a service that needs a real
deployment) is usually **a chain of systems**, not one call: package → deploy → bring up →
assert, one system per stage, and asynchronous.

**This needs no special support: one pipeline = N evals, one per stage.**

```jsonc
// <goal>/evals.json — one per stage, four stages
{"evals": [
  {"eval_id": "RAE-0001", "activation_round": 1, "system": "sys-build"},
  {"eval_id": "RAE-0002", "activation_round": 1, "system": "sys-deploy"},
  {"eval_id": "RAE-0003", "activation_round": 1, "system": "sys-run"},
  {"eval_id": "RAE-0004", "activation_round": 1, "system": "sys-assert"}]}

// <round>/evidence/runtime/acceptance-evals.json — what this round actually ran
{"entries": [
  {"eval_id": "RAE-0001", "outcome": "pass", "frozen_system": "sys-build",  "…": "…"},
  {"eval_id": "RAE-0002", "outcome": "pass", "frozen_system": "sys-deploy", "…": "…"},
  {"eval_id": "RAE-0003", "outcome": "fail", "frozen_system": "sys-run",    "…": "…"},
  {"eval_id": "RAE-0004", "outcome": "skipped", "frozen_system": "sys-assert", "…": "…"}]}
```

Under this ledger, a `decision.md` declaring `Feedback: positive` is **refused** — the third
stage failed. **A missed run is caught the same way**: an eval listed in `frozen_due_set` with
no matching entry in the ledger is refused too.

`frozen_system` records which system each stage actually ran against — once four stages are
chained together, **not recording the system means you can't tell which link broke.**

**Verdicts must be pulled back and written into this round's `evidence/`.** Remote records get
overwritten, cleaned up, rerun; if a round's verdict still points at the remote, that round's
conclusion drifts with it. **Pulling it back isn't overhead — it's the precondition for a round
being replayable.**

## What it cannot do

This section is not a disclaimer — it is the project's design stance. **The mechanical gate
reads files the agent wrote itself. It cannot verify motive, and it says so.**

- **It cannot prove an eval actually ran.** A hand-written `"outcome": "pass"` beside a
  fabricated artifact passes the same gate. What it buys is "citable, contestable under
  adversarial review" — not enforcement.
- **It does not read the review's prose.** It only records that a review happened and which
  file holds it.
- **It does not trigger or run any external system.** Packaging, deployment, bring-up, and
  data pulls are all done by your session, your CI, or your runner. **The referee never takes
  the field** — this is the other face of the same boundary that keeps it from proving
  anything "ran."
- Its own shipped documentation opens the boundary section with:
  **"The mechanical gate's exit code decides less than it looks like it decides."**
  And on the eval ledger, it says it **"does not prove the mechanical gate was ever actually run."**

Every one of those sentences lives in **the skill documentation shipped with the plugin**, not
only in this README. When a mechanism is found to claim more than it implements, that claim is
retracted, and the retraction itself is recorded.

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
  intake/
    .gitignore
  state/
    current.md
    environment.md
    control-contract.md
    evidence-index.md
    self-check.md
  meta/
    self-audit.md
    evolution-issues/
  evals/
    matrix.md
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

## Connecting External Systems And Credentials

### Channel inventory and connectivity checks are two different things

Harnessloop treats "channel inventory" and "connectivity checks" as two separate things:

- `$harnessloop-channels`: lists declared external systems, tools, MCP servers, CLIs, APIs, CI systems, databases, brokers, and credential references — listing only, never probing.
- `$harnessloop-connectivity`: runs only declared connectivity methods, and only once the required tool, endpoint/resource, credential reference, permission scope, parameters, and write-safety rules are all explicit.
- `$harnessloop-secrets`: creates and checks local-only channel parameter keys in `.harnessloop/local/channel-params.json`; values are never committed and never copied into evidence.

When a channel's self-check fails, is blocked, is skipped, or needs user confirmation because information is missing, Harnessloop must ask for the exact missing facts first — not try something else or push through regardless.

### Three files, three jobs

The single job of "how an external system plugs into this protocol" is actually split across three files, each owning one slice (`plugins/harnessloop/skills/harnessloop-loop/SKILL.md` has the fuller account of how these three divide the work):

- The `## Runtime Validation Systems` table in `.harnessloop/setup/data-sources.md`: prose describing **how to validate and what counts as passing** — this description exists only here; no mechanical gate ever reads it.
- `.harnessloop/setup/external-systems.json`: pure metadata declaring the **system id, interface class (`kind`), and the parameter names it needs** — nothing about how to judge the result.
- A round's own `evidence/runtime/acceptance-evals.json` ledger: records **what this round actually ran** — one entry per stage, with an `outcome`, and which declared system that eval ran against (`frozen_system`).

Each of the three files does its own job — prose for how-to-validate, static declaration, per-round actual record — and the protocol has never let them blur together.

### Why credentials cannot be written into it, by construction

In `.harnessloop/setup/external-systems.json`, each system has exactly four fields: `id`, `kind`, `description`, `params` — no URL field, no host field, no path field. `params` doesn't take values either, only parameter **names**, and only strings matching `^[A-Z][A-Z0-9_]{0,63}$` are accepted — that character set has no `/`, no `:`, no `.`, and no lowercase letters, so no matter how you assemble it, a URL, host, or path can never match that shape.

The actual values go through the channel-params that `$harnessloop-secrets` manages (`.harnessloop/local/channel-params.json`, already gitignored).

This is a **structural constraint** — there is simply nowhere in this declaration file for a credential to go. It is not "we're careful not to write it in."

### What `kind` describes: interface class, not role

`kind` currently takes the values `http` / `grpc` / `database` / `queue` / `filesystem` / `ssh` / `process` / `other`. This is a single axis — **what interface shape the caller uses to talk to the system** — not what role that system plays in some pipeline. A CI system, a device lab, a data platform each still declare `kind` by the interface shape they are actually accessed through (usually `http`, or `ssh`/`process` when executing commands remotely or locally), not by a role-named `kind` — the enum has no `ci` or `dataplatform` member, and never will. This is a recent, deliberate design decision — it is easy to get backwards on instinct, treating `kind` as "what this system is" rather than "how you talk to it."

## Skills

- `$harnessloop-init`: initialize `.harnessloop/` project files.
- `$harnessloop-setup`: complete or check environment detection, data sources, cost/context policy, and control-contract profile via the five-step setup wizard.
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

## Evidence Model

Harnessloop separates evidence artifact health from whether that evidence supports acceptance. A failed runtime test can be a valid evidence artifact and still produce negative feedback.

![Harnessloop evidence stack](docs/assets/evidence-stack.svg)

Evidence classes:

- `static`: real datasets, docs, reports, source-of-truth records.
- `dynamic`: generated data, sampled outputs, model/tool outputs.
- `runtime`: tests, CI, remote automation, probes, canaries, monitoring.
- `source`: repository source, schema files, source-data files.

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

## Cost Accountability

Harnessloop treats its own overhead as a first-class protocol measurement.
At every round close, `round_cost.py` settles token usage from local session
transcripts and writes an itemized `## Cost` section into the round summary:
input/cache/output tokens, a protocol-attribution estimate, and an optional
dollar figure from user-supplied rates. Gate interceptions — rounds rejected
by adversarial review, drift caught by self-audit — are recorded in decision
files so the protocol's cost and its catches sit in the same auditable
ledger.

Harnessloop does not claim the overhead pays for itself; it gives you the
bill, the interception record, and a judgment framework, and lets your own
project's data decide. See [docs/cost-model.md](docs/cost-model.md).

## Repository Map

- `docs/usage.md`: product-level usage guide and transfer packet prompt.
- `docs/harnessloop-framework.md`: framework design and detailed protocol.
- `docs/cost-model.md`: protocol overhead measurement and cost/benefit judgment framework.
- `docs/harnessloop-flow.mmd`: canonical detailed Mermaid flow source.
- `docs/harnessloop-flow.svg`: rendered detailed flow preview.
- `docs/assets/`: README and documentation visuals.
- `plugins/harnessloop/`: plugin source.
- `plugins/harnessloop/skills/`: installable skills and templates.
- `examples/mock-project/`: artificial reference project showing setup, intake, evidence, review, decision, self-audit, and evolution issue files.

### Validate

```bash
npm run validate
```

Or call the validator directly on any platform:

```bash
python scripts/validate.py
```

Wrapper scripts `scripts/validate.ps1` (Windows) and `scripts/validate.sh` (macOS/Linux) run the same Python validator.

The validator checks marketplace manifests, runs the init and secrets smoke tests, verifies documentation skeleton consistency against `init_project.py` (the single source of truth), enforces the mechanical protocol gates in `verify_protocol.py` against `examples/mock-project`, and runs Claude Code strict plugin validation. Set `HARNESSLOOP_SKIP_CLAUDE=1` to skip the Claude CLI step in environments where it is not installed.

If the Codex skill-creator toolkit is installed, its `quick_validate.py` can additionally lint each directory under `plugins/harnessloop/skills/`.

## Current Limits

- Harnessloop defines a protocol and skills; it does not yet provide a full shell CLI.
- It does not ship fixed data connectors. Projects must declare their own tools, accounts, data sources, and validation systems.
- The detailed flow should be maintained from `docs/harnessloop-flow.mmd`; generated or decorative imagery must not replace evidence-bearing flow diagrams.

Keep the plugin name as `harnessloop` in both manifests so marketplace selectors stay stable:

```text
harnessloop@harnessloop
```
