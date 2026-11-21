# SPEC-02 — Database schema

> **Status:** v1 (2026-11-01) · **Owner of:** every table and column

## 1. Extensions
`pgcrypto` for UUIDs.

## 2. `documents`

| Column | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `title` | text | not null |
| `shelf` | text | null allowed |
| `created_at`, `updated_at` | timestamptz | not null |

## 3. `loans`

| Column | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `document_id` | uuid | not null; FK → documents |
| `due_on` | date | not null |

## 4. `jobs`

| Column | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `kind` | text | not null |
| `payload` | jsonb | null |

## 7. Table → milestone map

| Table | Milestone |
|---|---|
| `documents` | M02 |
| `loans` | M02 |

## 8. Acceptance checks

1. Migrations apply to an empty database.
2. Every foreign key names an existing table.
