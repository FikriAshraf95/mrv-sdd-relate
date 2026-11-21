# DEC-002 — Write deviation→task and *affects* links to Markdown, or keep them graph-only

- **Date raised:** 2026-11-21 (spec audit) · **Needed by:** M01 (the deviation parser), at the latest M03 (`log_deviation`) · **Status:** Accepted (option A, 2026-11-21)
- **Specs affected:** [SPEC-02 §2 graph-only list, §4](../specs/SPEC-02-graph-schema.md#4-relationships), [SPEC-03 §5.1](../specs/SPEC-03-markdown-parsing.md#51-deviation-files), [SPEC-04 §5.1](../specs/SPEC-04-sync.md#51-edits), [SPEC-05 §5](../specs/SPEC-05-agent-tools.md#5-log_deviation), [DEVIATIONS.md](../DEVIATIONS.md) template

## Context

`log_deviation(task_id, …, affects=[…])` creates two relationships that the deviation file doesn't record:

- `RAISED_IN` → **Task** (the file only says the milestone: `**Date / milestone:** 2026-11-25 · M02`);
- `AFFECTS` → **File or Table** (the files and tables the deviation changed).

The audit made sure sync never deletes them by accident: they now carry `src = "tool"` and are on the canonical graph-only list (SPEC-02 §2). Being graph-only still means they are **lost** whenever the graph is rebuilt from Markdown:

- `sdd sync --reset` (after a schema change, or a corrupt store);
- a fresh clone with no committed store (see [DEC-001](DEC-001-committed-store.md));
- the sample and replay copies, which are rebuilt from the sample's Markdown.

They matter for the demo. `impact` on a table follows `Deviations that … AFFECTS the table` (SPEC-06 §2), and `explain` lists "deviations that AFFECTS it". Losing them weakens the "what shaped this code" answer, which is the centrepiece. It also goes against the project's own rule: *Markdown is the source of truth; the graph holds nothing a rebuild can't reproduce* (except claims, agents and events).

## Options

### A. Write them into the deviation file *(recommended)*
Two optional header fields, written by `log_deviation` and parsed by sync like any other field:

```markdown
- **Date / milestone:** 2026-11-25 · M02 · M02.3
- **Spec:** [SPEC-04 §2](../specs/SPEC-04-sync.md#2-incremental-sync)
- **Affects:** `src/sdd/sync/indexer.py`, `attachments`
- **Status:** Open
```

The task ID goes after the milestone. `Affects` lists file paths and table names in backticks; entries that don't resolve go to `unresolved`. Both relationships then get `src = <deviation file path>` and leave the graph-only list.

For: rebuildable, visible on GitHub, and a human writing a deviation by hand can fill them in too, so hand-written deviations get the same links. Stays within the "Markdown is the truth" rule.
Against: one more optional convention (both fields are optional, so the reference formats still parse with zero warnings); a template change in `DEVIATIONS.md`; slightly more parser work in M01.

### B. Keep them graph-only (current spec)
For: nothing to change; the file format stays exactly as the reference projects use it.
Against: everything in *Context*: the links vanish on every rebuild, and the demo's sample (rebuilt from Markdown) never has them unless its replay recreates them.

### C. Rebuild them from a durable event log
Persist Events to a committed `.sdd/events.jsonl` and replay it after a reset.
For: keeps the deviation file format untouched. Against: a second source of truth, merge conflicts on the log, and much more machinery than A for the same result.

## Recommendation

**A.** It is the smallest change that keeps the project's core rule, and it makes hand-written and tool-written deviations equal.

## If accepted

- **A:** `DEVIATIONS.md` template: add `**Affects:**` and show the task after the milestone. SPEC-03 §5.1: parse the optional task ID in **Date / milestone:** and the optional `**Affects:**` field. SPEC-02 §4: `RAISED_IN` source becomes "**Date / milestone:** field (milestone and optional task)", `AFFECTS` source becomes "**Affects:** field"; remove both from the graph-only list in SPEC-02 §2. SPEC-04 §5.1 and SPEC-05 §5: `log_deviation` writes both fields. Add a SPEC-03 acceptance check: a deviation with both fields yields `RAISED_IN` → Task and `AFFECTS`, and survives `sdd sync --reset`.
- **B:** remove the pointer in SPEC-02 §2; nothing else.
- **C:** a new section in SPEC-04 for the event log, its format and replay; SPEC-02 graph-only list unchanged.

## Decision
**2026-11-21, the user: accepted the recommendation.** `log_deviation` writes the task after the milestone in **Date / milestone:** and the files and tables in an optional **Affects:** field; sync parses both, so `RAISED_IN` → Task and `AFFECTS` are owned by the deviation file and rebuildable.

Applied in: `DEVIATIONS.md` template, SPEC-02 §2 (graph-only list) and §4, SPEC-03 §5.1 and new check 9 (tested in M04.11), SPEC-04 §2 (code File nodes in phase 1, so `AFFECTS` resolves in the same batch) and §5.1, SPEC-05 §5.
