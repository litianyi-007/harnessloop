# Runtime Test Output

Command:

```text
npm test -- --runInBand
```

Observed result:

```text
FAIL generated order summary includes all required fields
Expected field: totalAmount
Received fields: orderId, status
```

Interpretation:

Runtime behavior does not satisfy the expected generated summary shape.

