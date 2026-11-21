# SPEC-03 — Lending rules

> **Status:** v1 (2026-11-01) · **Owner of:** loan length, renewals, reminders

## 1. Loans
A loan lasts 14 days.

## 2. Catalogue import
CSV rows become `documents`.

## 10. Acceptance checks

1. A loan lasts 14 days.
2. A member can hold five loans.
3. A second renewal is refused.
4. An overdue loan is flagged.
5. A returned loan is closed.
6. A reserved book cannot be renewed.
7. A loan keeps its original due date after a failed renewal.
8. Imports skip empty rows.
9. Imports report duplicate titles.
10. Reminders go out once a day.
11. Reminders stop after return.
12. The loan list is sorted by due date.
