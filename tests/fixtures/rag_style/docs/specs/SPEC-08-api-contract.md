# SPEC-08 — API contract

> **Status:** v1 (2026-11-01) · **Owner of:** endpoints and error codes

## 1. Endpoint index
See section 4.

## 4. Loans

### 4.1 List loans
`GET /loans`.

### 4.6 Renew a loan
`POST /loans/{id}/renew` extends `due_on` by 14 days.

### 4.7 Return a loan
`POST /loans/{id}/return` closes the loan.
