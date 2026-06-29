# Eval Matrix Template

```markdown
# Harnessloop Eval Matrix

Use this matrix to test whether the local harness loop policy is robust enough for expected project scenarios.

| Dimension | Cases to cover | Current coverage | Risk | Required hardening |
| --- | --- | --- | --- | --- |
| Task type | code development, data research, financial/strategy analysis, long-cycle research, production validation, cross-system integration | | | |
| Evidence type | static, dynamic, runtime, source, human confirmation | | | |
| Data state | complete, partially missing, stale, schema drift, semantic drift, source conflict, inaccessible | | | |
| External dependency | none, single, multiple, cascading, unstable, behavior changed | | | |
| Reproducibility | fully reproducible, partially reproducible, remote observation only, human validation only, unreproducible | | | |
| Feedback class | positive, negative-execution, negative-assumption, neutral-insufficient-evidence, blocked-human-decision | | | |
| Rollback ability | no state change, directly reversible, compensating rollback, irreversible but isolatable, human-approved rollback | | | |
| Time span | single round, short multi-round, long multi-round, cross-session resume, periodic re-baseline needed | | | |
| Change boundary | single file, single variable, same module, cross-module, cross-system, contract change | | | |
| Acceptance risk | low auto-continue, medium review, high human confirmation, failure prohibits execution | | | |
| Evidence quality | path exists, trusted source, valid timestamp, sufficient summary, raw evidence traceable, review reproducible | | | |
| Cost/context pressure | small context, long logs, large data, parallel agents, summary compression, raw evidence kept out of main session | | | |
```

