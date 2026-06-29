# Feedback Policy

- Positive: runtime test passes and adversarial review cites valid evidence.
- Negative: test fails, review finds missing runtime evidence, or review finds validation drift.
- Neutral: evidence is inconclusive or cannot be reproduced.
- Blocked runtime-recoverable: runtime state blocks the original action, but read-only investigation can continue.
- Blocked access-missing: required data or runtime access is unavailable.
- Blocked write-safety-required: cleanup, rollback, trigger, or external mutation needs confirmation.
