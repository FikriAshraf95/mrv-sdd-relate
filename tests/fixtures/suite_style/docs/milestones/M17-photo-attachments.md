# M17 — Photo attachments

> **Depends on:** [M02](M02-stock-basics.md) technically (scheduled after [M16](M16-order-flow.md)) · **Blocks:** nothing directly
> **Read first:** [SPEC-18 §5](../specs/SPEC-18-attachments.md#5-sharing) (whole section) and
> [§2.4](../specs/SPEC-18-attachments.md#24-streaming) (streaming) →
> [SPEC-02 `file_shares`](../specs/SPEC-02-database-schema.md#file_shares) ·
> [SPEC-06 §7](../specs/SPEC-06-stock-and-orders.md#7-ordering)
> **Model:** Sonnet, with Opus review.

## Goal
Staff attach photos to plant batches and share one photo by link.

## Tasks
### Backend
- [x] Store uploaded photos on disk
  under the configured folder, keyed by the batch id
  - keep the original file name
  - reject files over ten megabytes
- [x] Stream photos to the browser ([SPEC-18 §2.4](../specs/SPEC-18-attachments.md#24-streaming))
### Tests
- [x] [SPEC-18 §6](../specs/SPEC-18-attachments.md#6-acceptance-checks) 6.

## Acceptance criteria
1. A staff member can attach a photo to a batch.
2. A share link opens one photo.

**Status: DONE (2026-11-01), with two follow-ups.** Thumbnails are made on first view.
Deviations: [D021](../deviations/D021-photo-thumbnails.md).
- Open: thumbnail size is not configurable yet.
