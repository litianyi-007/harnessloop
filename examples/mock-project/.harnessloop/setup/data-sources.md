# Data Sources

## Static Sources

| Source | Access | Freshness | Drift risk | Validation |
| --- | --- | --- | --- | --- |
| `fixtures/orders.csv` | repository file | refreshed manually before each goal | schema change | compare header to `docs/order-schema.md` |

## Dynamic Sources

| Source | Access | Freshness | Drift risk | Validation |
| --- | --- | --- | --- | --- |
| generated order summary | local script output | per round | generated rules change | compare against runtime test output |

## Runtime Systems

| System | Access | Validation method | Human setup required |
| --- | --- | --- | --- |
| local test command | shell | `npm test -- --runInBand` | no |

## External Tools

No external accounts are required for this sample.

