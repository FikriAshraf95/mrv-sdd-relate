# M02 — Ingestion

> **Depends on:** [M01](M01-timer.md)
> **Read first:** [SPEC-02 §2](../specs/SPEC-02-ingest-schema.md#2-documents) · [SPEC-02 §3](../specs/SPEC-02-ingest-schema.md#3-chunks)
> **Model:** Sonnet. Small and mechanical.

## Goal
Load documents and cut them into chunks.

## Tasks
### Backend
- [ ] **M02.1** Loader that stores `documents` ([SPEC-02 §2](../specs/SPEC-02-ingest-schema.md#2-documents))
- [ ] **M02.2** Chunker that fills `chunks` (after M02.1)
### Tests
- [ ] **M02.3** [SPEC-02 §4](../specs/SPEC-02-ingest-schema.md#4-acceptance-checks) checks 1–2 (after M02.2)

## Acceptance criteria
1. A loaded document has at least one chunk.

**Status:**
