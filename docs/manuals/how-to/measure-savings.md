# Measure the savings on your own repo

> **For:** anyone who wants numbers for their own repo, not just the sample's.

`sdd bench` runs three measurements. Each works on a **temporary copy** of your project, so your files and store are never touched. Each prints a table and writes `<date>.json` and `<date>.md` to `bench/results/` (change with `--out`).

## Context per task

```bash
sdd bench context                         # every milestone
sdd bench context --milestone M05a        # only some (repeatable)
```

For every task it compares:

- **markdown**: what an agent reads by the usual token rule: root CLAUDE.md + the whole milestone file + each *Read first* target (whole file when marked, otherwise the referenced sections' line ranges) + `DEVIATIONS.md` + every deviation file amending a read section + the plan file;
- **milestone**: the graph's `get_context(detail="milestone")`, the same sections without the surrounding files;
- **task**: the default packet.

The output has one row per task (characters for each variant), then the averages and the saving. On the Courtside sample, the averages were:

| Variant | Avg chars | Avg tokens | vs Markdown |
|---|---:|---:|---:|
| Markdown (token rule) | 8034 | 2009 | |
| Graph, `detail=milestone` | 4806 | 1202 | −40.2% |
| Graph, `detail=task` | 3118 | 780 | −61.2% |

Tokens are estimated as characters ÷ 4. With `ANTHROPIC_API_KEY` set in the environment, `--exact` counts them with Anthropic's token-counting API instead (this sends the text to the API).

## Session restart

```bash
sdd bench restart
```

Applies a scripted set of edits (two section edits, one deviation, three completed tasks), then compares re-reading CLAUDE.md, the active milestone, `DEVIATIONS.md` and every changed Markdown file against one `what_changed` call.

## Parallel collisions

```bash
sdd bench collisions --agents 10 --tasks 30 --runs 5
```

Compares 10 threads ticking boxes with read-modify-write of one milestone file (naive) against the same agents using `claim_task` / `complete_task`. Expected: some lost ticks for naive, and exactly 0 double claims and 0 lost ticks for the graph.

## Reading your numbers

- **Small repos save less.** The sample's specs are short, so the task packet saves 61%. This repo, with longer specs, saves 72%. The bigger your specs and *Read first* lists, the bigger the saving.
- **A task with no saving links no sections.** Fix the task line ([how](link-tasks-to-sections.md)) and re-run.
- **`always_include` costs every task.** If the default `SPEC-00 §6` is long, or you added more, it adds to every packet.
