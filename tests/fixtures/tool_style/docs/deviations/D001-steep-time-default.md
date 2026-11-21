# D001 — Default steep time is configurable

- **Date / milestone:** 2026-11-02 · M01 · M01.2
- **Spec:** [SPEC-01 §1](../specs/SPEC-01-timer.md#1-brewing)
- **Affects:** `src/kettle/brew.py`, `brews`
- **Status:** Open

## Spec says
The default steep time is fixed per tea.

## Implementation does
The default comes from a setting.

## Why
Tasters disagree about green tea.

## Consequences
Tests set the setting explicitly.
