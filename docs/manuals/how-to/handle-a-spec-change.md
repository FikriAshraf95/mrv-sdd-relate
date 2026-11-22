# Handle a spec change from a client or PM

> **For:** whoever owns the specs when a requirement changes ("cancelled bookings must be kept for the audit trail").

A spec change is a person editing the spec. No tool changes spec prose. SDD Graph's job is to tell you what the change touches before you make it, and to tell every agent about it afterwards.

## 1. See what the change will touch

Before editing, ask what depends on the section:

```bash
sdd impact "SPEC-03 §4"
```

or, in the dashboard, **Impact** → `SPEC-03 §4`. For a section you get:

- **tasks_open / tasks_done**: tasks governed by the section. Done tasks may need rework; open tasks will build the new rule.
- **milestones**: milestones whose *Read first* includes it.
- **deviations**: deviations that already amend it. The change may resolve one of them.
- **tables, features → files, tests**: the code and checks likely to change.
- child sections and sections that link to it.

If the change is about data, start from the table instead: `sdd impact bookings` or `sdd impact bookings.cancelled_at`.

## 2. Edit the spec

Edit the section in your editor, as usual, while the daemon runs. Within about a second the daemon:

- re-parses the file and updates that section's text (and only that section's: editing §4 doesn't mark §4.1 or §3 as changed),
- sets the section's `changed_at` and records a `section_changed` event,
- re-resolves links if you renamed or renumbered headings (renumbering changes section IDs, so prefer adding a new section at the end over renumbering).

## 3. Decide what happens to existing work

| Situation | Do |
|---|---|
| The new rule matches what the code already does because of a deviation | Resolve that deviation: set its status to **Resolved → spec updated**, update its index row, and remove its note from the spec ([how](log-a-deviation.md#resolving-a-deviation-later)) |
| Done tasks built the old rule | Add **new tasks** for the rework, with the next free numbers, in the current or a new milestone. Don't untick old tasks: they were done against the spec of their day, and their history stays in the events |
| Open tasks build this section | Nothing. Their next `get_context` includes the new text |
| Agents are mid-task on it | Tell them, or let them find out: their next `what_changed` lists the section under `sections_changed` |

New task lines link the changed section, like any other: `- [ ] **M06.4** Keep cancelled bookings for the audit trail ([SPEC-03 §4](…)) (after M06.2)`.

## 4. Agents pick it up

Every agent starts its session with `what_changed(since="last_session", agent=…)`. The changed section appears there under `sections_changed`, with when it changed. The next `get_context` for any task governed by it carries the new full text.

## 5. Commit

Commit the spec edit, any new tasks and any resolved deviations together, with a message that says why (`docs: keep cancelled bookings (request from the hall manager)`).

## Spec change or deviation?

- **The rule changes for everyone, from now on:** spec change (this page).
- **The code had to differ from the spec for a reason found while building:** deviation ([Log a deviation](log-a-deviation.md)). It can become a spec change later by being resolved.
- **A choice the specs don't settle:** a decision record in your own format. SDD Graph indexes it as a Doc if you list its path in `docs` in `.sdd/config.toml`.
