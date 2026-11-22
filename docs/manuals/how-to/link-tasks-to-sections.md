# Write task lines that get small context packets

> **For:** anyone writing milestones. **Why it matters:** this one habit decides most of the token saving.

## The rule

**Every task line links the spec sections it implements.**

```markdown
- [ ] **M03a.3** The overlap rule, checked inside the insert transaction ([SPEC-03 §3](../specs/SPEC-03-booking-rules.md#3-overlap-rule), [SPEC-02 `bookings`](../specs/SPEC-02-database-schema.md#bookings)) (after M03a.2)
```

`get_context("M03a.3")` then puts **SPEC-03 §3 and the `bookings` table section in full** into the packet, lists the milestone's other *Read first* sections only by title in `outline`, and adds the open deviations that amend those sections.

## What happens without links

A task that links nothing gets the milestone's whole *Read first* list in full instead. That's no smaller than an agent reading the files by hand. Measured on the sample and on this repo:

| Task line | Typical packet |
|---|---|
| links 1–2 sections | 3–15 k characters |
| links nothing | the same as the Markdown token rule (no saving) |

## Ways to reference a section

All of these work, in link text or plain text:

| Write | Means |
|---|---|
| `SPEC-03 §3` | section 3 of SPEC-03 **and its subsections** |
| `SPEC-03 §3.2` | just §3.2 (and its subsections) |
| `SPEC-03 §3–4` or `§3–§4` | §3 and §4 (siblings between both ends) |
| `SPEC-03 §2, §5` or `§2 and §5` | two sections |
| ``SPEC-02 `bookings` `` | the section whose title is `bookings` (numbered or not) |
| `SPEC-03` or `SPEC-03 (whole file)` | the whole spec |
| `SPEC-04 §4 checks 1–3` | `VERIFIES` links to acceptance checks 1, 2 and 3 of SPEC-04 |

Prefer a Markdown link (`[SPEC-03 §3](../specs/…#3-overlap-rule)`), so the line still works on GitHub. If a link has both an anchor and `§` text, **the text wins**.

## Also worth adding

- **`(after M03a.2)`** at the end of the line, so `next_tasks` doesn't offer the task too early.
- **Backticked file paths and table names** (`` `src/booking/overlap.py` ``, `` `bookings` ``) in the task text. They become `MENTIONS` links, so the packet's `code` part lists those files and tables.
- **`always_include`** in `.sdd/config.toml` for sections every task needs (your global conventions). The default is `["SPEC-00 §6"]`; a reference that doesn't resolve is skipped. See [Configuration](../reference/configuration.md).
- **Test tasks that name checks** (`SPEC-03 §6 checks 1–3`) pull that spec's *Acceptance checks* section into the packet.

## Check your packets

```bash
sdd context M03a.3                 # prints the packet and its size
sdd context M03a.3 --json          # the raw JSON
sdd bench context                  # every task: Markdown vs graph, in characters and tokens
```

`sdd context` ends with a line like `3122 chars (~781 tokens)`. A task whose packet is near the milestone's full reading list probably links nothing.
