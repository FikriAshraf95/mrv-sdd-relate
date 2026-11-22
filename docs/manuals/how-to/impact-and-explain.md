# Find what a change affects (`impact`) and why a file exists (`explain`)

> **For:** developers planning a change, reviewers, and agents that need code context.

## `impact`: if this changes, what else is affected?

```bash
sdd impact bookings                # a table
sdd impact bookings.ends_at        # a column
sdd impact "SPEC-03 §4"            # a section (and its subsections)
sdd impact SPEC-03                 # a whole spec
sdd impact M05a.2                  # a task
sdd impact M05a                    # a milestone
sdd impact src/booking/cancel.py   # a file
sdd impact booking                 # a feature (name or slug)
sdd impact D006                    # a deviation
sdd impact bookings --depth 2      # fewer hops (1 to 5, default 3)
```

Dashboard: **Impact** tab, type the target, **Show impact**. Deep link: `http://localhost:8770/#impact/table%3Abookings` (the target percent-encoded). MCP: `impact(target="bookings", depth=3)`.

### Reading the result

Results come in fixed groups: `specs`, `sections`, `milestones`, `tables` (columns too), `features` (domains too), `files`, `tasks_open`, `tasks_done`, `deviations`, `tests`, `commits`. Each group holds up to 50 items, and `counts` gives the full totals. CLI output:

```
table:bookings (Table) bookings
specs (5)
  SPEC-03  Booking rules
      via table:bookings <-USES_TABLE feature:booking ->SPECIFIED_BY SPEC-03
…
deviations (4)
  D003  Cancelled bookings are kept with cancelled_at [open]
      via …
```

**`via`** is the chain of relationships from the target to the item, read left to right. `<-TYPE` means the arrow points toward the left node, `->TYPE` away from it. So `table:bookings <-USES_TABLE feature:booking ->SPECIFIED_BY SPEC-03` reads: "the Booking feature uses the `bookings` table, and SPEC-03 specifies that feature". Each item keeps its shortest chain.

### What each target follows

| Target | Follows |
|---|---|
| Table | its columns, tables whose columns reference it, the defining section and spec, sections/tasks/deviations mentioning it, features using it → their files and specs, tasks governed by those sections, commits completing those tasks, deviations amending those sections or affecting the table, tests of the defining spec's checks |
| Section / Spec | child sections, sections linking to it, milestones reading it, tasks governed by it (open and done), deviations amending it, tables it defines or mentions, its spec's features → files, its spec's checks → test files |
| File | features implemented in it → specs, sections and tasks mentioning it, tasks touching it, the 10 latest commits changing it → tasks they complete, deviations affecting it, checks it tests |
| Task | its milestone, governing sections, tasks it waits on and tasks waiting on it, files it touched, commits completing it, deviations raised in it |
| Milestone | its tasks, what it reads, milestones it depends on and that depend on it, deviations raised in it, commits part of it |
| Feature | its files, tables, specs, domain, and the section traversal over its specs |
| Deviation | what it amends and affects, the milestone and task it was raised in |

### Ambiguous names

A bare name can match several things (a table and a feature both called `payments`). Then you get `ambiguous_target` (exit code 2) with the candidates as prefixed IDs. Repeat with one of them:

```bash
sdd impact table:payments
sdd impact feature:payments
```

Prefixes: `table:`, `column:<table>.<col>`, `file:`, `feature:`, `domain:`.

## `explain`: why does this file exist?

```bash
sdd explain src/booking/overlap.py
sdd explain overlap.py              # a unique tail of the path is enough
```

Dashboard: **Explain** tab, pick the file in the tree. MCP: `explain(path="src/booking/overlap.py")`.

You get a summary paragraph, then groups with `via` chains:

```
src/booking/overlap.py implements feature Booking (Courts), specified by SPEC-03. Built by M03a.3
(commits 2e7084d). Named in SPEC-03#3. Shaped by D003 (open): Cancelled bookings are kept with
cancelled_at; D001 (resolved): …
features (1)   feature:booking
sections (1)   SPEC-03#3  Overlap rule
tasks (1)      M03a.3 … [done]
commits (1)    2e7084d  feat: overlap rule [M03a.3]
deviations (3) D003 [open], D001 [resolved], D002 [resolved]
```

A file with every group empty is **orphan code**: nothing in the specs, tasks or history explains it. The summary says so, and that's worth knowing too.

## `find_code`: which files belong to this?

```bash
sdd find --table bookings                    # files of features using it, files mentioned with it, migrations/models naming it
sdd find --feature booking
sdd find --domain courts
sdd find --spec SPEC-03
sdd find --text cancel                       # substring of the path
sdd find --table bookings --feature booking  # several options intersect
```

Up to 50 files, sorted by path, each with `via`.

## Make the answers richer

These answers are only as good as the links in your repo:

- **Feature lines** in spec headers connect specs to code: `> **Feature:** Booking · **Domain:** Courts · **Implements:** `src/booking/**` · **Tables:** bookings, courts` ([format](../reference/repo-format.md#feature-lines)).
- **Schema tables** in a schema spec (a heading named after the table, followed by a table whose first column is `Column`) create Table and Column nodes.
- **Commit messages that name the task** (`feat: overlap rule [M03a.3]`) link commits to tasks and files.
- **`files_touched` in `complete_task`** records the files each task changed.
- **Backticked paths and table names** in specs and task lines become `MENTIONS`.
- **Test names after checks** (`test_spec03_ac2_…`) link test files to acceptance checks.
