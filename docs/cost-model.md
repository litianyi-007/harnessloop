# Harnessloop Cost Model

Harnessloop asks projects to pay a real protocol overhead: state files are
read before actions, every round writes evidence and review files, and
adversarial review costs tokens. This document defines how that overhead is
measured, how the return side is recorded, and how to judge whether the
trade is reasonable for a given project.

Honesty rule for this document: the **measurement machinery is shipped and
real**; the **judgment thresholds are priors awaiting calibration** from real
project data. Numbers are labeled as one or the other. Harnessloop does not
claim the protocol pays for itself until the return side is measured — see
[../product-feedback.md](../product-feedback.md) (P1-2) for that commitment.

## The three-part argument

Harnessloop's cost story has three parts. Each has its own metric:

```
eval matrix ................ designs what the gates check
      |                      (coverage vs missed-catch record)
      v
gate chain ................. performs interceptions
      |    ^                 (interception count = the "payout")
      |    |
      |    delegation matrix + cost-context policy
      |    (keeps each interception cheap)
      v
round_cost.py .............. bills the overhead
                             (protocol-attributed tokens = the "premium")

           ROI = payouts / premiums
```

- **Premium** (measured, automated): what the protocol costs per round.
  `scripts/round_cost.py` settles token usage from local session transcripts
  at every round close and writes it into `round-summary.md`.
- **Payout** (recorded manually, see below): what the protocol catches.
  Every time a gate rejects a round, adversarial review refutes a claim, or
  self-audit stops a drift, that is an interception — work that would
  otherwise have shipped wrong and been redone later.
- **Coverage** (recorded manually, see below): whether the gates check the
  right things. The eval matrix is not a runtime gate; its value shows up as
  the ratio of failure modes it anticipated versus missed.

## Premium: measuring the overhead

At each round close, the loop protocol runs:

```bash
python <plugin-root>/skills/harnessloop-loop/scripts/round_cost.py --project <target-project>
```

It aggregates API usage (input / cache-write / cache-read / output tokens)
recorded in local Claude Code session transcripts since the last settlement
marker, and emits a `## Cost` markdown block for `round-summary.md`.
Computation is fully local and deterministic; transcript files must never be
read into the model context — only the short summary enters the session.

Details that matter when reading the numbers:

- **Protocol attribution is a heuristic.** Turns whose content mentions
  `.harnessloop` are counted as protocol-attributed. This over-counts rounds
  that discuss the protocol and under-counts overhead buried in unrelated
  turns. Treat it as an estimate, not an audit.
- **Nominal tokens overstate dollar cost.** Repeated protocol-state reads
  mostly hit the prompt cache, and cache reads are typically ~10x cheaper
  than fresh input. Report the dollar figure (via
  `.harnessloop/local/cost-prices.json`, user-supplied rates) alongside the
  token figure; the dollar share of protocol overhead is usually well below
  the token share.
- **Historical data settles as one lump.** The first settlement covers all
  existing transcripts; per-round attribution starts from that point
  forward. Use `--reset` to skip history, `--dry-run` to peek without
  settling.

One real measurement exists so far: this repository's own development
sessions showed **14% of output tokens protocol-attributed** (33 of 435
assistant turns). That is a skewed sample — the sessions were *developing*
the protocol, not running business work through it — but it is a measured
number, not a guess.

## Payout: recording interceptions

The premium side is automated; the payout side requires one manual habit.
Without it, the ROI has a denominator and no numerator.

**When a gate intercepts** — adversarial review rejects the round, the
evidence gate refuses stale evidence, `verify_protocol.py` flags a scope
violation, self-audit catches drift, the intake gate blocks an unsafe
takeover — record in that round's `decision.md`:

- What was caught, with the evidence path.
- **Estimated rework avoided** if it had shipped: usually "one round"
  (re-execute + re-review) unless the miss would have propagated further.

**When a gate misses** — a defect surfaces in a later round that an earlier
gate should have caught — record two things:

- A payout-side entry of the actual rework cost (the rounds spent fixing it).
- A coverage-side entry: did the eval matrix anticipate this failure mode?
  - If **no**: add the missing row to `evals/matrix.md`. The miss is an eval
    coverage gap; the matrix earns its keep by shrinking this category.
  - If **yes**: the gap is in gate execution (weak review prompt, vague
    threshold), not eval design. Fix the template or prompt; if the flaw is
    in Harnessloop itself, file an evolution issue.

This no/yes split is what makes the eval matrix's value measurable at all:
misses in uncovered scenarios argue for better coverage; misses in covered
scenarios argue for better enforcement.

## Keeping the premium low

Two protocol mechanisms exist specifically to hold the premium down; if
costs look unreasonable, check these first:

- **The delegation matrix** requires adversarial review to be delegated.
  Reviewers receive bounded file paths and a template — not the main
  session's accumulated context — so the most expensive gate runs in the
  cheapest way. `setup/cost-context-policy.md` additionally assigns cheaper
  model tiers to review roles where available.
- **File-based evidence** keeps raw logs and reports out of the main
  session. Self-audit's "cost/context runaway" check exists to catch
  violations of exactly this rule.

## Judging the numbers: prior bands

These bands are **priors, not measured conclusions**. Calibrate them against
your own project after 5–10 rounds and replace this table with your data.

| Protocol share of round cost | Reading | Action |
| --- | --- | --- |
| < 10% | Negligible | None |
| 10–25% | Insurance-premium range; reasonable for the target workload (multi-day, cross-session, high-risk) | Operate normally |
| 25–50% | Warning: either the task is too small for the protocol, or the protocol is being misused | Check self-audit's cost/context runaway item; consider whether this task belongs in Harnessloop at all |
| > 50% | Unreasonable: the protocol has become the task | Stop; this workload is on the "do not use" list for a reason |

Break-even arithmetic (a formula, not a claim): if the protocol share is
*p* and one interception saves roughly one round of rework, the protocol
pays for itself when it intercepts at least one genuine miss per `1/p`
rounds — e.g. at 20% share, one interception per 5 rounds breaks even.
Whether that rate is actually achieved is an empirical question that only
the interception record can answer.

## Reading the ledger

- Per round: the `## Cost` section of each `round-summary.md`, next to the
  round's scope, evidence, and decision.
- Mid-round: `round_cost.py --dry-run` at any time.
- Per goal: sum the rounds —
  `grep -A7 "## Cost" .harnessloop/goals/*/rounds/*/round-summary.md`,
  or use `--json` for machine processing.
- Payouts: interception and miss entries in each round's `decision.md`.

When enough rounds have accumulated, replace the prior bands above with
measured ones and publish the result. Until then, Harnessloop's public claim
is limited to what is true today: the overhead is measured, the judgment
framework exists, and the verdict is pending data.
