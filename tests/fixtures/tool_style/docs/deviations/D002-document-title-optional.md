# D002 — Document titles may be empty

- **Date / milestone:** 2026-11-03 · M02 · M02.1
- **Spec:** [SPEC-02 §2](../specs/SPEC-02-ingest-schema.md#2-documents)
- **Affects:** `src/ingest/loader.py`, `documents`
- **Status:** Open

## Spec says
Every document has a title.

## Implementation does
The loader accepts a document without a title and stores an empty string.

## Why
Scanned files arrive untitled.

## Consequences
Search shows the file name instead.
