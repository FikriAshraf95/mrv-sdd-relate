# Log a deviation

> **For:** agents and developers whose code knowingly departs from a spec. **Rule:** an unlogged deviation is a bug. Log it in the same change as the code.

## When to log, and when not to

**Log** when a spec instruction is impossible or wrong in practice, when two sections contradict each other and you picked one, when you chose a materially different approach (library, data shape, API contract), or when you deliberately skipped a spec item.

**Don't log** naming or formatting the specs don't dictate, or bug fixes that move code *closer* to the spec. If the rule itself should change before anyone builds it, change the spec instead ([Handle a spec change](handle-a-spec-change.md)).

## With the MCP tool (agents)

Pass the task the deviation is raised in (normally the one you hold; a claim isn't required) and a one-line title. Call:

```json
log_deviation({
  "task_id": "M05a.2",
  "agent": "sonnet-2",
  "title": "A promoted waitlist entry holds the slot for 15 minutes",
  "amends": ["SPEC-05 §2"],
  "spec_says": "Promotion creates a confirmed booking for the oldest waiting member.",
  "implementation_does": "Promotion creates a booking with status `held`. The member has 15 minutes to confirm.",
  "why": "Members offered a slot at night never saw it, and the slot stayed blocked.",
  "consequences": "`held` becomes a booking status and the overlap rule counts held bookings.",
  "affects": ["bookings", "waitlist_entries", "src/waitlist/promote.py"]
})
```

- `amends` takes one or more spec references ([grammar](../reference/repo-format.md#spec-references)). Each must resolve, or you get `unknown_section`.
- `affects` is optional: project file paths and table names. Each must name a file in the project or a table defined in your schema spec, else `invalid_input`.
- `status` defaults to `"open"`. Use `"resolved"` only if you're also updating the spec in the same change.

Result: `{"id": "D006", "path": "docs/deviations/D006-a-promoted-waitlist-entry-holds-the-slot-for-15-minutes.md", "amends": ["SPEC-05#2"], "files": [...], "synced_at": "..."}`.

## With the CLI (people and scripts)

```bash
sdd deviation M05a.2 --agent me \
  --title "A promoted waitlist entry holds the slot for 15 minutes" \
  --amends "SPEC-05 §2" \
  --spec-says "Promotion creates a confirmed booking for the oldest waiting member." \
  --does "Promotion creates a booking with status held; 15 minutes to confirm." \
  --why "Members offered a slot at night never saw it." \
  --consequences "held becomes a booking status." \
  --affects bookings --affects src/waitlist/promote.py
```

`--amends` and `--affects` repeat. `--resolved` sets the status to resolved.

## What write-back changes in your files

All of it happens in one atomic job, so a parallel agent can't take the same number:

**1. A new file** `docs/deviations/D006-a-promoted-waitlist-entry-holds-the-slot-for-15-minutes.md`, filled from the template under `## Template` in your `DEVIATIONS.md` (or a built-in one):

```markdown
# D006 — A promoted waitlist entry holds the slot for 15 minutes

- **Date / milestone:** 2026-11-12 · M05a · M05a.2
- **Spec:** [SPEC-05 §2](../specs/SPEC-05-waitlist-and-reminders.md#2-promotion)
- **Affects:** `bookings`, `waitlist_entries`, `src/waitlist/promote.py`
- **Status:** Open

## Spec says
Promotion creates a confirmed booking for the oldest waiting member.

## Implementation does
…
```

The number is the highest D-number in the files **and** the index, plus one.

**2. A row at the top of the index** in `docs/DEVIATIONS.md` (it replaces a `*(none yet)*` placeholder row):

```markdown
| [D006](deviations/D006-….md) | A promoted waitlist entry holds the slot for 15 minutes | M05a | [SPEC-05 §2](…) | Open |
```

**3. A note at the end of each amended section** in the spec, after a blank line:

```markdown
> **DEVIATION:** see [D006](../deviations/D006-….md) — A promoted waitlist entry holds the slot for 15 minutes
```

When a whole spec is amended, the note goes at the end of its header blockquote.

**In the graph:** a Deviation node with `AMENDS` to the section, `RAISED_IN` to the milestone and task, and `AFFECTS` to the files and tables. Because the task and the affects list are written into the file, a rebuild reproduces these links.

**For other agents:** every agent whose context includes SPEC-05 §2 now sees D006 (with what the implementation does) in its next `get_context` and in `what_changed`.

Commit the three edits with your code.

## Resolving a deviation later

When the deviation should become the rule:

1. Edit the spec section so it says what the code does.
2. In the deviation file, set `- **Status:** Resolved → spec updated`, and update the index row's status.
3. Remove the `> **DEVIATION:** see [D006]…` note from the spec.
4. Commit. The daemon re-syncs and the deviation shows as `resolved`. Resolved deviations appear in packets by title only, since the spec now says it.

There is no tool for this on purpose: changing spec text is a person's decision.

## If it fails

| Error | Fix |
|---|---|
| `unknown_section` | an `amends` reference doesn't resolve. Check it with `sdd section "SPEC-05 §2"` |
| `invalid_input` on `affects` | an entry names no file and no defined table. Fix the path (project-relative, forward slashes) |
| `writeback_disabled` | `writeback = false` in `.sdd/config.toml`. Deviations need write-back, because one that exists only in the graph would contradict the Markdown |
| `source_changed` | someone edited the target section away meanwhile. Re-read and retry |
