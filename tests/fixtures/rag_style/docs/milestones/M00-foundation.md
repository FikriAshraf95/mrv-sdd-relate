# M00 — Foundation and contracts

> **Depends on:** — · **Blocks:** everything
> **Read first:** [SPEC-00 §6](../specs/SPEC-00-overview.md#6-global-conventions) · [SPEC-02 (whole file)](../specs/SPEC-02-database-schema.md)
> **Model:** Opus. Every later milestone builds on these contracts.

## Goal
Lay the repository layout and the database schema.

## Tasks
### Backend
- [ ] `git init`, `.gitignore`, `.env.example` ([SPEC-11 §2](../specs/SPEC-11-deployment.md#2-environment-variables)).
- [ ] Migrations for every table in [SPEC-02](../specs/SPEC-02-database-schema.md): `documents`,
  `loans` and `jobs`.
### Tests
- [ ] SPEC-02 §8 checks 1–2 (migrations)

## Acceptance criteria
1. A fresh clone builds.
2. Migrations apply to an empty database.

**Status:**
