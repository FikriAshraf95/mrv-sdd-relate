# D021 — Thumbnails are generated lazily

- **Date / milestone:** 2026-11-01 · M17
- **Spec:** [SPEC-18 §5](../specs/SPEC-18-attachments.md#5-sharing)
- **Status:** Open

## Spec says
Thumbnails exist as soon as a photo is uploaded.

## Implementation does
The first request creates the thumbnail.

## Why
Uploads from the greenhouse tablets were slow.

## Consequences
The first view of a photo is slower.
