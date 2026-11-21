# Deviations

A deviation is any place where the code knowingly differs from a spec. **An unlogged deviation is a bug.**

Each deviation is **its own file** in [deviations/](deviations/). This page holds the rules, the template and the index. From M03 on, prefer the `log_deviation` MCP tool: it does steps 1–4 below in one atomic change and can't collide with a parallel agent.

## When to log
- A spec instruction is impossible or wrong in practice (a Relate or MCP SDK limitation, for example).
- Two spec sections contradict each other and you had to pick one.
- A materially different approach: library, graph shape, tool or endpoint contract.
- A spec item deliberately skipped.

## When not to log
- Naming or formatting the specs don't dictate.
- Bug fixes that move code closer to the spec.

More than a couple of deviations in one milestone means the *Read first* list needs re-reading.

## How
1. Before writing, check the **highest D-number** in the index below; take the next one (never reuse a number).
2. Create `deviations/D<nnn>-<kebab-title>.md` from the template, **in the same change as the code**.
3. Add a row at the **top** of the index.
4. At the spec section, add: `> **DEVIATION:** see [D<nnn>](../deviations/D<nnn>-….md) — one-line summary`.
5. If it should become the rule: update the spec instead, set the deviation's status to **Resolved → spec updated**, and remove the note from the spec.

Open deviations are folded into the specs at M99 (and whenever one spec collects several).

## Template

```markdown
# D<nnn> — <title>

- **Date / milestone:** 2026-11-?? · M0? · M0?.? (task optional)
- **Spec:** [SPEC-0? §?](../specs/SPEC-0?-….md#…)
- **Affects:** `src/sdd/…`, `<table>` (optional: files and tables this changes)
- **Status:** Open | Resolved → spec updated

## Spec says
…

## Implementation does
…

## Why
…

## Consequences
…
```

## Index (newest first)

| # | Title | Milestone | Spec | Status |
|---|---|---|---|---|
| [D001](deviations/D001-store-copies-keep-lock-markers.md) | Committed store copies keep the `.cypherlite.lock` markers | M00b | [SPEC-08 §3](specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots) | Resolved → spec updated |
