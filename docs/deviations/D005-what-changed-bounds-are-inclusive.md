# D005 — what_changed bounds are inclusive

- **Date / milestone:** 2026-11-21 · M03a · M03a.3
- **Spec:** [SPEC-05 §7](../specs/SPEC-05-agent-tools.md#7-what_changed)
- **Affects:** `src/sdd/service/changes.py`
- **Status:** Open

## Spec says
last_session returns everything after the previous Agent.last_changes_at value.

## Implementation does
The start bound is inclusive (at >= since) for last_session and for ISO times. An event ID as since is exclusive (events after that event).

## Why
Event times have one-second resolution. An exclusive bound would lose for good any change made in the same second as the previous what_changed call; an inclusive one at worst reports it twice.

## Consequences
Two calls within the same second can list the same item twice. Agents treat the result as at-least-once.
