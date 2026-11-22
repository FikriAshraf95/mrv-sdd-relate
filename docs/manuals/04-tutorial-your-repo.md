# 4. Tutorial: adopt SDD Graph on your own repo

> **For:** developers who want SDD Graph on a real spec-driven repo, driven by Claude Code. **Time:** 30–45 minutes. **You need:** your repo (a git repository), [uv](https://docs.astral.sh/uv/), and [Claude Code](https://claude.com/claude-code).

This tutorial follows one path from start to finish. It installs `sdd` with uv. If you'd rather keep Python off your machine (or the install fails on your platform), install it with Docker as described in [Install `sdd`, option B](how-to/install.md#option-b-docker-no-python-on-the-host). Every command below then works the same with the Docker prefix.

At the end you will have the daemon serving your repo, Claude Code connected to it, and one milestone run by an orchestrator and one subagent.

---

## Step 1: install `sdd`

```bash
uv tool install --python 3.13 git+https://github.com/FikriAshraf95/mrv-sdd-relate.git
sdd --version
```

**You should see:**

```
sdd 0.1.0
relate-db 1.2.0
```

uv downloads Python 3.13 if you don't have it. `sdd` needs Python 3.13 exactly, and `relate-db` ≥ 1.2 must have a wheel for your platform (it has none for Alpine/musl).

## Step 2: check your repo layout

SDD Graph reads this layout by default:

```
your-repo/
  docs/
    specs/SPEC-01-something.md         one spec per file; ## headings are sections
    milestones/M01-first-thing.md      one milestone per file; - [ ] task lines
    milestones/done/                   optional: finished milestones move here
    milestones/M01-plan.md             optional plan file for M01
    deviations/D001-some-title.md      optional at first; created by log_deviation
    DEVIATIONS.md                      the deviation index (with a template)
  CLAUDE.md
  src/…, tests/…                       your code
```

What matters:

- **Spec files** are named `SPEC-<number>-<anything>.md` and start with `# SPEC-01 — Title`. Each `##`, `###` and `####` heading is a section. A leading number (`## 2. Making a booking`) becomes its address, `SPEC-01 §2`.
- **Milestone files** are named `M<number>[letter]-<anything>.md` (`M02-…`, `M05a-…`) and start with `# M02 — Title`. Each task is a checkbox line.
- **Deviation files** are named `D<3+ digits>-<anything>.md`.

Different folder names are fine: `sdd init` (next step) detects where your files are, and you can set any glob in `.sdd/config.toml` ([Configuration](reference/configuration.md)). The full format rules are in [Repo format](reference/repo-format.md).

`docs/DEVIATIONS.md` is optional: the first `log_deviation` creates it with a built-in template. If you want your own rules and template in it, create it now. `log_deviation` copies the fenced block under the heading `## Template` exactly, and inserts its rows at the top of the table whose first header cell is `#`:

````markdown
# Deviations

Any place where the code knowingly differs from a spec. An unlogged deviation is a bug.

## Template

```markdown
# D<nnn> — <title>

- **Date / milestone:** YYYY-MM-DD · M0? · M0?.? (task optional)
- **Spec:** [SPEC-0? §?](../specs/SPEC-0?-….md#…)
- **Affects:** `src/…`, `<table>` (optional)
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
| *(none yet)* | | | | |
````

## Step 3: `sdd init`

From the repo root:

```bash
cd your-repo
sdd init
```

**You should see** something like:

```
 created  .sdd/config.toml
 created  .sdd/.gitignore
 created  .mcp.json
 created  .claude/skills/sdd/SKILL.md
detected  specs = docs/specs/SPEC-*.md
detected  milestones = docs/milestones/**/M*.md
detected  plans = docs/milestones/**/M*-plan.md
detected  deviations = docs/deviations/D*.md
detected  deviation_index = docs/DEVIATIONS.md

Add this to CLAUDE.md:

## Agents (SDD Graph)
…
```

What each file is:

| File | Purpose | Commit it? |
|---|---|---|
| `.sdd/config.toml` | the document globs it detected; edit to override | yes |
| `.sdd/.gitignore` | keeps the live store (`graph/`), `daemon.json` and lock files out of git | yes |
| `.mcp.json` | registers the `sdd` MCP server for Claude Code at `http://localhost:8770/mcp`. If the file already existed, the `sdd` entry was **merged** in and your other servers kept | yes |
| `.claude/skills/sdd/SKILL.md` | the agent protocol as a Claude Code skill | yes |

**Copy the printed snippet into your CLAUDE.md.** It tells every Claude Code session to use the tools instead of reading spec files. (The [Guide for agents](agents.md#copy-paste-claudemd-block) has a longer version.)

`sdd init` never overwrites anything without `--force`, so running it twice is harmless.

## Step 4: give every task a stable ID (`sdd ids`)

Agents claim tasks by ID, so each task line needs one: `**M02.3**` right after the checkbox. If your milestone files have plain checkbox lines, preview the rewrite first:

```bash
sdd ids
```

**You should see** a diff per milestone file:

```diff
-- [ ] Hash and re-parse only changed files
+- [ ] **M02.3** Hash and re-parse only changed files
```

IDs are numbered after the highest existing number in each file, and lines that already have one are never renumbered. Apply it:

```bash
sdd ids --write          # asks before writing; add --yes to skip the question
```

**You should see** `wrote N task IDs in M file(s)`. From now on, a new task takes the next free number wherever you insert it, and numbers are never reused.

While you're editing milestones, two small habits pay off:

- **Link the sections each task implements** in the task line: `- [ ] **M02.3** Hash and re-parse only changed files ([SPEC-04 §2](../specs/SPEC-04-sync.md#2-incremental-sync))`. This is the single biggest factor in packet size ([why](how-to/link-tasks-to-sections.md)).
- **State order with `(after …)`** at the end of the line: `(after M02.1)` or `(after M02.1, M02.2)`. `next_tasks` won't offer a task until the ones it waits on are done.

And give each milestone a header so the graph knows what to read and what comes first:

```markdown
# M02 — Sync daemon

> **Depends on:** [M01](done/M01-parsers.md)
> **Read first:** [SPEC-04 §1–2](../specs/SPEC-04-sync.md#1-watcher) · [SPEC-02 §4](../specs/SPEC-02-schema.md#4-relationships)
> **Model:** Opusplan
```

## Step 5: `sdd doctor`

```bash
sdd doctor
```

`doctor` parses your Markdown without touching any store, and lists every warning and unresolved link. **You should see** a final summary like:

```
7 specs, 42 sections, 8 milestones, 30 tasks, 6 deviations, 8 tables, 39 columns, 9 references, 0 legacy task lines, 0 unresolved links
warnings: 0 error, 0 warning, 0 info
```

It exits with code 1 if anything is an `error`. Common warnings and fixes:

| Warning | Means | Fix |
|---|---|---|
| `task_unstable_id` | a task line has no `**M02.3**` ID | `sdd ids --write` |
| `task_duplicate_id` (error) | two tasks share an ID in one file | renumber one to the next free number |
| `task_id_mismatch` | `**M03.1**` sits in the M02 file | fix the ID's milestone part |
| `bad_filename` (error) | a file matched a glob but has no `SPEC-NN`/`M<nn>`/`D<nnn>` in its name | rename it, or narrow the glob in `.sdd/config.toml` |
| unresolved link | a link or `SPEC-03 §9` points at nothing (renamed section, unwritten spec) | fix the link, or leave it: it resolves once the target exists |
| `deviation_index_mismatch` | a deviation file has no index row, or the other way round | add the missing row or file |

The full list is in [Troubleshooting](troubleshooting.md#sdd-doctor-warnings) and [Repo format](reference/repo-format.md#warning-codes). You don't need zero warnings to continue, but fix errors and unresolved links in the milestone you're about to run.

## Step 6: start the daemon

In a terminal you'll leave open:

```bash
sdd daemon
```

**You should see** the startup sync (files scanned, nodes created), then Uvicorn listening on `http://127.0.0.1:8770`. The first sync of a fresh store records the current state without generating events, so `what_changed` doesn't fill with "changes" that happened before the tool existed.

In a second terminal, check it:

```bash
sdd info      # project, store, "daemon: running on :8770", node counts per label
sdd status    # milestones with their tasks, claims, warnings
```

Open **<http://localhost:8770>**: your milestones are on the Board, and your specs are in the Graph tab.

Leave the daemon running while you work. It picks up your edits within about a second (Markdown) to ten seconds (code), and new commits within 3 seconds.

## Step 7: connect Claude Code

Start Claude Code in the repo root. It reads `.mcp.json` and connects to the `sdd` server (approve the server if it asks). Check with `/mcp`: **you should see** `sdd` as connected, with 14 tools: `status`, `next_tasks`, `claim_task`, `release_task`, `get_context`, `read_section`, `log_deviation`, `complete_task`, `complete_milestone`, `what_changed`, `impact`, `explain`, `find_code`, `query`.

Quick test. Ask Claude:

> Call the sdd `status` tool and tell me which milestone is next.

## Step 8: run your first milestone with an orchestrator and one subagent

Pick the first milestone that isn't done (say `M02`). In the main Claude Code session (the **orchestrator**, agent name `opus-orch`), say:

> You are the orchestrator, agent name `opus-orch`. Start with `what_changed(since="last_session", agent="opus-orch")`. Then `status` and `next_tasks(milestone="M02")`. Launch **one** subagent for the first claimable task. Tell it: its agent name is `sonnet-1`, its task ID, and to follow `.claude/skills/sdd/SKILL.md` as a worker. When it reports back, review the diff and run the tests. Then do the next task the same way, until `next_tasks` is empty. Don't edit checkboxes by hand.

What happens, step by step:

1. The orchestrator calls `what_changed` (first call: last 24 h), `status` and `next_tasks`. It gets M02.1, plus any other task whose `(after …)` tasks are done.
2. It launches subagent `sonnet-1` with "task M02.1".
3. The subagent calls **`claim_task("M02.1", agent="sonnet-1")`**. On the Board, the card moves to *In progress* with a `sonnet-1` chip.
4. It calls **`get_context("M02.1", agent="sonnet-1")`** and reads the packet: the linked sections in full, the outline of the rest, open deviations, related code. If the outline lists something it needs, it calls `read_section`.
5. It builds and tests. If it must depart from the spec, it calls **`log_deviation`**: the deviation file, index row and spec note appear in your working tree.
6. It commits (naming the task: `feat: walker [M02.1]`) and calls **`complete_task("M02.1", agent="sonnet-1", notes=…, files_touched=[…], commit=…)`**. The box in `M02-….md` becomes `[x]`, the card moves to *Done*, and the result lists the tasks this unblocked.
7. The orchestrator reviews and moves on to the next task.

When every task is done and you've checked the acceptance criteria, tell the orchestrator:

> Verify M02's acceptance criteria, then call `complete_milestone("M02", agent="opus-orch", verification="<how you verified it>")`.

The daemon writes `**Status:** DONE (<today>). <verification> Deviations: <list or none>.` into the milestone file, moves it to `docs/milestones/done/` (if that folder exists), and fixes every link to it. Review the changes and commit them.

> **If a subagent crashes or goes silent** holding a claim, the orchestrator frees it with `release_task("M02.1", agent="opus-orch", force=true)` and relaunches. See [Free a stuck claim](how-to/free-a-stuck-claim.md).

## Step 9: next session

Start every new session (and every subagent) with:

```
what_changed(since="last_session", agent="<the same name as last time>")
```

It returns what moved since that agent's previous call, including sections a person edited, deviations logged and tasks completed, instead of re-reading the docs.

---

## What you have now

- A **graph of your repo** in `.sdd/graph/` (gitignored), kept current by the daemon as you and your agents edit files and commit.
- **Stable task IDs** in every milestone, and a clean `sdd doctor`.
- **Claude Code wired to MCP**, with the protocol in `.claude/skills/sdd/SKILL.md` and your CLAUDE.md.
- **Atomic claims**: two agents can't take the same task, and their checkbox edits can't collide.
- **Small context packets** instead of whole spec files.
- **A live Board** at `http://localhost:8770`, plus Impact and Explain for your own code.
- **Markdown still the source of truth**: everything the agents did is in your files and git history.

## Where to go next

- Run several workers at once: [Parallel subagents](how-to/parallel-subagents.md).
- Make packets smaller: [Link tasks to sections](how-to/link-tasks-to-sections.md).
- See what a change will touch before you make it: [Impact and explain](how-to/impact-and-explain.md).
- Keep CLAUDE.md's status block current automatically: [Export diagrams and the status block](how-to/export-diagrams-and-status.md).
- Measure the token savings on your repo: [Measure savings](how-to/measure-savings.md).
