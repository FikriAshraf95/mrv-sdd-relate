# DEC-004 — What the sample is if private-repo-app can't be published

- **Date raised:** 2026-11-21 (spec audit) · **Needed by:** M06 (Fri 5 Dec), but the content takes time, so ideally now · **Status:** Accepted (option A, as the only sample; 2026-11-21)
- **Specs affected:** [SPEC-00 §8](../specs/SPEC-00-overview.md#8-schedule-and-open-items) O1, [SPEC-11 §5](../specs/SPEC-11-deployment-and-demo.md#5-sample-project), [M06a](../milestones/M06a-sample-and-exports.md) M06a.1

## Context

The judges explore a sample project (`samples/<name>/`). Open item **O1** asks whether private-repo-app content may be published in this public repo. SPEC-11 §5 lists three answers, **and all three publish its docs**:

| O1 answer | Publishes |
|---|---|
| Full | docs, code, real git history |
| Docs + tree (current default) | docs, file paths, commit messages and dates |
| Docs only | docs, plus an invented code tree |

There is no plan for **"no, publish nothing"**. CLAUDE.md already forbids publishing anything before O1 is answered. If the answer comes late or is "no", M06 (scheduled Fri 5 Dec, a week before the deadline) has no sample at all. A good sample needs real work: specs, milestones with task IDs, deviations, a code tree, a git history, and above all **a table with a long history**, so `impact` on it is the impressive demo shot (SPEC-00 §7 criterion 5).

## Options

### A. Add an invented sample and make it the default until O1 is answered *(recommended)*
A small, believable project written from scratch in the office-suite format (it grows from the `suite_style` fixture of M01): for example a "team notes and file sharing" app with about 6 specs (one schema spec with 6–8 tables), 8 milestones (some letter-suffixed, some done), about 6 deviations, a code tree of placeholder files under features, and a git history scripted by `scripts/make_sample.py` (commits naming tasks, a rebase-free linear history). Its story is designed so one table (say `attachments`) is touched by several specs, milestones and deviations.

If O1 later comes back "yes", `make_sample.py` takes a `--source` option and builds the real one instead; the invented sample stays as a test fixture.
For: no risk of publishing anything, it can start now, and the demo story is under our control. Against: half a day to a day of content work; less "real" than a production repo.

### B. Keep "Docs + tree" as the default; build the invented sample only if O1 is "no"
For: no extra work if the answer is yes. Against: a late "no" leaves M06 scrambling.

### C. Use this repo's own docs as the sample
For: no extra content, and it is honest dogfooding. Against: there is no schema spec and no tables, so the `impact` table demo can't happen; the history is short; few deviations.

## Recommendation

**A.** It removes the dependency on O1 from the critical path. Answering O1 still matters: a "yes" upgrades the sample, and a "no" costs nothing.

## If accepted

- **A:** SPEC-00 §8 O1: add the option "None: an invented sample". SPEC-11 §5 table: add the row "None (**default until answered**): an invented project in the office-suite format, built by `scripts/make_sample.py`", and drop "default" from "Docs + tree". SPEC-11 §5 centrepiece: "a table with a long history (in the invented sample, chosen by design; in private-repo-app, `attachments`)". M06.1: build the invented sample unless O1 has been answered with a publishable option. Possibly a new task in M01 or M04 to grow the `suite_style` fixture towards it.
- **B:** SPEC-11 §5: add the "None" row as a fallback only.
- **C:** SPEC-11 §5: the sample is this repo; SPEC-00 §7 criterion 5 changes to a non-table target.

## Decision
**2026-11-21, the user: private-repo-app cannot be made public, so we invent the sample.** This answers O1 with "no" and makes option A the only plan rather than a default: there is no `--source` switch to real content, and nothing specific to private-repo-app (text, file names, commit messages, structure) may appear in the sample, the fixtures or any commit. Only its generic conventions are reused.

Applied in: SPEC-00 §7 item 2 and §8 (O1 closed), SPEC-10 §3, SPEC-11 §5 (rewritten: format, size, scripted history, designed centrepiece table, built store) and the `.env.example` `SAMPLE`, M06.1, CLAUDE.md status and *Never break*.
