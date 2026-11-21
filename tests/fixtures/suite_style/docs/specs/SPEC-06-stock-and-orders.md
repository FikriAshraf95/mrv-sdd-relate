# SPEC-06 — Stock and orders

> **Spec ID:** SPEC-06 · **Consumed by:** SPEC-18

## 1. Stock
Each batch has a count.

## 7. Ordering

1. Totals are computed once for the whole order.
  > **DEVIATION:** see [D012](../deviations/D012-line-rounding.md) — rounding happens per line.
2. A confirmed order reserves stock.
