# SPEC-02 — Database schema

> **Spec ID:** SPEC-02 · **Consumed by:** SPEC-03, SPEC-06, SPEC-18
> **Related:** [SPEC-00 §6 conventions](SPEC-00-overview.md#6-conventions)

## 1. Identity ([SPEC-03](SPEC-03-staff-and-access.md))

### users

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| email | text not null | unique |

## 2. Files ([SPEC-18](SPEC-18-attachments.md))

### attachments

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| uploaded_by | uuid not null | → users [restrict] |
| ts | timestamptz | not null |

> > **DEVIATION:** see [D018](../deviations/D018-share-expiry.md) — links expire after seven days.

### file_shares

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| attachment_id | uuid not null | → attachments |

## 13. Table → milestone map

| Table | Milestone |
|---|---|
| users | M02 |
| attachments | M17 |
