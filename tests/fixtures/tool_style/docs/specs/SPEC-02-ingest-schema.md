# SPEC-02 — Ingestion schema

> **Status:** v1 (2026-11-03) · **Owner of:** document storage
> **Feature:** Ingestion · **Domain:** Library · **Implements:** `src/ingest/**` · **Tables:** documents, chunks

## 1. Overview

Documents are split into chunks. Each chunk keeps the text it was cut from.

## 2. `documents`

> **DEVIATION:** see [D002](../deviations/D002-document-title-optional.md)

| Column | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `title` | text | not null |
| `created_at` | timestamptz | not null |

## 3. `chunks`

| Column | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `document_id` | uuid | `FK → documents`, not null |
| `body` | text | not null |

## 4. Acceptance checks

1. A loaded document gets a creation time.
2. A document is split into at least one chunk.
3. Every chunk points at its document.
