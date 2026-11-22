"""M06a.2: build the Courtside sample's git history, its built store and its snapshot copies.

Run it inside the dev container (it needs git, and the ``relate`` CLI for the snapshot copies):

    docker compose -f docker-compose.dev.yml exec dev uv run python scripts/make_sample.py

``samples/courtside/`` holds the sample's *final* files (docs and placeholder code). This script

1. fills the status block of its CLAUDE.md (``sdd export --claude-status``);
2. replays a scripted linear history of about forty commits in a temp repository, with fixed
   authors and dates (so the SHAs are the same on every run), checks that the tip tree equals
   ``samples/courtside/`` byte for byte, and bundles it as ``samples/courtside.bundle``;
3. clones the bundle, runs ``sdd sync`` on the clone into ``samples/courtside/.sdd/graph`` (the
   sample's built store, committed on purpose, DEC-001) and ``sdd snapshot`` into
   ``samples/courtside/.sdd/snapshots``;
4. checks the result (zero doctor warnings, every ``impact bookings`` group filled, no temp path
   in the readable JSON copy) and prints a summary.

Nothing here comes from a real project: the story is invented (SPEC-11 §5).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sdd import config
from sdd.graph import store
from sdd.service import commands, impact, indexing, snapshot
from sdd.service.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "courtside"
BUNDLE = ROOT / "samples" / "courtside.bundle"
SKIP_DIRS = {".sdd", "__pycache__", ".pytest_cache"}
# demo tooling (SPEC-11 §5): read by `sdd demo`, not part of Courtside's history, not in the bundle
SKIP_FILES = {"replay.toml"}

NADIA = "Nadia Okafor <nadia.okafor@courtside.example>"
TOMAS = "Tomás Reyes <tomas.reyes@courtside.example>"
MEI = "Mei Lin Chua <mei.lin.chua@courtside.example>"

MILESTONES = {
    "M01": "docs/milestones/done/M01-skeleton-and-members.md",
    "M02": "docs/milestones/done/M02-courts-and-schema.md",
    "M03a": "docs/milestones/done/M03a-booking-core.md",
    "M03b": "docs/milestones/done/M03b-cancellations.md",
    "M04": "docs/milestones/done/M04-payments.md",
    "M05a": "docs/milestones/M05a-waitlist.md",
    "M05b": "docs/milestones/M05b-reminders.md",
    "M06": "docs/milestones/M06-reports-and-audit.md",
}
DEVIATIONS = {
    1: "docs/deviations/D001-opening-hours-are-per-court-not-per-hall.md",
    2: "docs/deviations/D002-bookings-store-an-end-time-not-a-duration.md",
    3: "docs/deviations/D003-cancelled-bookings-are-kept-with-cancelled-at.md",
    4: "docs/deviations/D004-late-refunds-are-partial.md",
    5: "docs/deviations/D005-payment-is-taken-at-check-in.md",
    6: "docs/deviations/D006-a-promoted-waitlist-entry-holds-the-slot-for-15-minutes.md",
}
SPECS = [f"docs/specs/{p.name}" for p in sorted((SAMPLE / "docs" / "specs").glob("SPEC-*.md"))]
SPEC_02 = "docs/specs/SPEC-02-database-schema.md"
INDEX = "docs/DEVIATIONS.md"
CLAUDE = "CLAUDE.md"
MODEL = "src/booking/model.py"
MIG_COURTS = "migrations/0002_courts.sql"
MIG_BOOKINGS = "migrations/0003_bookings.sql"
MIG_PAYMENTS = "migrations/0004_payments.sql"
SCHEMA_TEST = "tests/test_schema.py"
BOOKING_TEST = "tests/test_booking.py"
CAPTURE = "src/payments/capture.py"
OVERRIDES = "src/booking/overrides.py"

# ---------------------------------------------------------------- earlier versions of files

MODEL_V1 = '''"""The booking row (SPEC-02 `bookings`, SPEC-03 §2)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Booking:
    id: str
    member_id: str
    court_id: str
    starts_at: datetime
    duration_minutes: int = 60
'''
MODEL_V2 = MODEL_V1.replace(
    "    duration_minutes: int = 60\n",
    '    duration_minutes: int = 60\n    status: str = "confirmed"\n',
)
MODEL_V3 = '''"""The booking row (SPEC-02 `bookings`, SPEC-03 §2)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Booking:
    id: str
    member_id: str
    court_id: str
    starts_at: datetime
    ends_at: datetime
    status: str = "confirmed"
'''
SCHEMA_TEST_V1 = """from pathlib import Path

MIGRATIONS = Path(__file__).parent.parent / "migrations"


def test_spec02_ac1_foreign_keys_are_indexed():
    sql = "\\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    for column in ("opening_hours (court_id)", "bookings (member_id)"):
        assert column in sql


def test_spec02_ac3_member_with_bookings_cannot_be_deleted():
    sql = (MIGRATIONS / "0003_bookings.sql").read_text()
    assert "references members (id) on delete restrict" in sql
"""


# ---------------------------------------------------------------- stage helpers


def plain(text: str, removed: bool) -> str:
    return re.sub(r"\n{3,}", "\n\n", text) if removed else text


def notes(text: str, keep: set[int]) -> str:
    """The text with the ``**DEVIATION:**`` note lines of deviations not in ``keep`` removed."""
    out, removed = [], False
    for line in text.split("\n"):
        found = re.search(r"\[D(\d+)\]", line)
        if "**DEVIATION:**" in line and found and int(found[1]) not in keep:
            removed = True
            continue
        out.append(line)
    return plain("\n".join(out), removed)


def spec02(final: str, keep: set[int]) -> str:
    """SPEC-02 as it read before the deviations in ``keep`` were logged (notes and columns)."""
    text = notes(final, keep)
    if 1 not in keep:
        text = text.replace(
            "| court_id | uuid not null | → courts [cascade] |\n| weekday", "| weekday"
        )
    if 2 not in keep:
        text = text.replace(
            "| ends_at | timestamptz | not null |", "| duration_minutes | int | not null |"
        )
    if 3 not in keep:
        text = text.replace("| cancelled_at | timestamptz | null while the booking stands |\n", "")
    if 6 not in keep:
        text = text.replace("held, confirmed or cancelled", "confirmed or cancelled")
    return text


def unticked(text: str, done: set[str]) -> str:
    """A milestone file with only the tasks in ``done`` ticked and no DONE status."""

    def box(m: re.Match[str]) -> str:
        return f"- [{'x' if m['id'] in done else ' '}] **{m['id']}**"

    text = re.sub(r"- \[[ x]\] \*\*(?P<id>M\d+[a-z]?\.\d+)\*\*", box, text)
    return re.sub(r"^\*\*Status: DONE.*$", "**Status:**", text, flags=re.M)


def index_rows(text: str, keep: set[int]) -> str:
    lines = [
        ln
        for ln in text.split("\n")
        if not (m := re.match(r"\| \[D(\d+)\]", ln)) or int(m[1]) in keep
    ]
    return "\n".join(lines)


def empty_status_block(text: str) -> str:
    return re.sub(r"(<!-- sdd:status -->\n).*?(<!-- /sdd:status -->)", r"\1\2", text, flags=re.S)


def cut_before(text: str, marker: str) -> str:
    return text.split(marker, maxsplit=1)[0]


# ---------------------------------------------------------------- the scripted history


@dataclass(frozen=True)
class Step:
    when: str
    author: str
    message: str
    files: dict[str, str] = field(default_factory=dict)  # path -> text written in this commit

    @property
    def name(self) -> str:
        return self.author.split(" <")[0]

    @property
    def email(self) -> str:
        return self.author.split(" <")[1].rstrip(">")


def build_steps(final: Callable[[str], str]) -> list[Step]:  # noqa: PLR0915 - one line per commit
    steps: list[Step] = []
    done: dict[str, set[str]] = {}

    def add(
        when: str,
        author: str,
        message: str,
        *,
        paths: tuple[str, ...] = (),
        stages: dict[str, str] | None = None,
        task: str | None = None,
        close: str | None = None,
    ) -> None:
        files = {p: final(p) for p in paths}
        files.update(stages or {})
        if task:
            ms = task.split(".")[0]
            done.setdefault(ms, set()).add(task)
            files[MILESTONES[ms]] = unticked(final(MILESTONES[ms]), done[ms])
        if close:
            files[MILESTONES[close]] = final(MILESTONES[close])
        steps.append(Step(when, author, message, files))

    def devs(*keep: int) -> dict[str, str]:
        """The deviation index and the specs with the notes of deviations ``keep``."""
        k = set(keep)
        out = {INDEX: index_rows(final(INDEX), k), SPEC_02: spec02(final(SPEC_02), k)}
        for spec in SPECS:
            if spec != SPEC_02:
                out[spec] = notes(final(spec), k)
        return out

    ms_files = {MILESTONES[m]: unticked(final(MILESTONES[m]), set()) for m in MILESTONES}

    # --- M01
    first = {**devs(), **ms_files, CLAUDE: empty_status_block(final(CLAUDE))}
    add(
        "2026-09-08T10:00:00",
        NADIA,
        "docs: initial specs, milestones and overview",
        stages=first,
        paths=("README.md", "docs/deviations/README.md"),
    )
    add("2026-09-08T11:30:00", NADIA, "chore: ignore python caches", paths=(".gitignore",))
    add(
        "2026-09-09T09:15:00",
        TOMAS,
        "chore: package skeleton and config [M01.1]",
        paths=("pyproject.toml", "src/members/__init__.py"),
        task="M01.1",
    )
    add(
        "2026-09-11T14:20:00",
        TOMAS,
        "feat: members table and sign-up [M01.2]",
        paths=("src/members/signup.py", "migrations/0001_members.sql"),
        task="M01.2",
    )
    add(
        "2026-09-15T10:05:00",
        TOMAS,
        "feat: roles and session token [M01.3]",
        paths=("src/members/roles.py",),
        task="M01.3",
    )
    add(
        "2026-09-17T16:40:00",
        MEI,
        "test: spec 01 checks 1-3 [M01.4]",
        paths=("tests/test_members.py",),
        task="M01.4",
    )
    add("2026-09-18T09:30:00", NADIA, "docs: close M01 [M01]", close="M01")
    # --- M02
    add(
        "2026-09-21T11:00:00",
        TOMAS,
        "feat: courts table and the hall's six courts [M02.1]",
        paths=("src/booking/__init__.py",),
        task="M02.1",
        stages={MIG_COURTS: cut_before(final(MIG_COURTS), "\ncreate table opening_hours")},
    )
    add(
        "2026-09-24T15:10:00",
        TOMAS,
        "feat: opening hours per court [M02.2]",
        paths=("src/booking/hours.py", MIG_COURTS),
        task="M02.2",
    )
    add(
        "2026-09-24T15:45:00",
        NADIA,
        "docs: D001 opening hours are per court [M02.2]",
        paths=(DEVIATIONS[1],),
        stages=devs(1),
    )
    add(
        "2026-09-26T10:30:00",
        TOMAS,
        "feat: bookings migration and model [M02.3]",
        task="M02.3",
        stages={
            MODEL: MODEL_V1,
            MIG_BOOKINGS: notes_free_migration(final(MIG_BOOKINGS), ends=False, cancelled=False),
        },
    )
    add(
        "2026-09-30T09:00:00",
        MEI,
        "test: schema checks 1 and 3 [M02.4]",
        task="M02.4",
        stages={SCHEMA_TEST: SCHEMA_TEST_V1},
    )
    add("2026-09-30T17:00:00", NADIA, "docs: close M02 [M02]", close="M02")
    # --- M03a
    add(
        "2026-10-05T10:00:00",
        TOMAS,
        "feat: slot grid [M03a.1]",
        paths=("src/booking/slots.py",),
        task="M03a.1",
    )
    add(
        "2026-10-08T13:25:00",
        TOMAS,
        "feat: create a booking [M03a.2]",
        task="M03a.2",
        stages={MODEL: MODEL_V2},
    )
    add(
        "2026-10-09T09:40:00",
        NADIA,
        "docs: D002 bookings store an end time [M03a.2]",
        paths=(DEVIATIONS[2],),
        stages={
            **devs(1, 2),
            MODEL: MODEL_V3,
            MIG_BOOKINGS: notes_free_migration(final(MIG_BOOKINGS), ends=True, cancelled=False),
        },
    )
    add(
        "2026-10-11T15:50:00",
        TOMAS,
        "feat: overlap rule [M03a.3]",
        paths=("src/booking/overlap.py",),
        task="M03a.3",
    )
    add(
        "2026-10-13T11:15:00",
        MEI,
        "test: spec 03 checks 1-3 [M03a.4]",
        task="M03a.4",
        stages={BOOKING_TEST: booking_test_v1(final(BOOKING_TEST))},
    )
    add(
        "2026-10-14T09:00:00",
        NADIA,
        "docs: close M03a [M03a]",
        close="M03a",
        paths=("docs/milestones/done/M03a-plan.md",),
    )
    # --- M03b
    add(
        "2026-10-17T10:20:00",
        TOMAS,
        "feat: cancel a booking [M03b.1]",
        task="M03b.1",
        paths=("src/booking/cancel.py", MIG_BOOKINGS),
        stages={
            MODEL: final(MODEL).replace(
                '("held", "confirmed", "cancelled")', '("confirmed", "cancelled")'
            )
        },
    )
    add(
        "2026-10-17T11:05:00",
        NADIA,
        "docs: D003 cancelled bookings are kept [M03b.1]",
        paths=(DEVIATIONS[3],),
        stages=devs(1, 2, 3),
    )
    add(
        "2026-10-21T14:30:00",
        TOMAS,
        "feat: desk overrides [M03b.2]",
        task="M03b.2",
        stages={OVERRIDES: unformatted_overrides(final(OVERRIDES))},
    )
    add(
        "2026-10-23T16:00:00",
        MEI,
        "test: cancellation and overlap checks [M03b.3]",
        task="M03b.3",
        paths=(BOOKING_TEST, SCHEMA_TEST),
    )
    add("2026-10-24T09:30:00", NADIA, "docs: close M03b [M03b]", close="M03b")
    # --- M04
    add(
        "2026-10-28T10:10:00",
        TOMAS,
        "feat: surface rates and prices [M04.1]",
        task="M04.1",
        paths=("src/payments/__init__.py", "src/payments/prices.py"),
    )
    add(
        "2026-11-02T13:00:00",
        MEI,
        "feat: take payment for a booking [M04.2]",
        task="M04.2",
        stages={
            CAPTURE: unformatted_capture(final(CAPTURE)),
            MIG_PAYMENTS: cut_before(final(MIG_PAYMENTS), "\ncreate table refunds"),
        },
    )
    add(
        "2026-11-02T14:15:00",
        NADIA,
        "docs: D005 payment is taken at check-in [M04.2]",
        paths=(DEVIATIONS[5],),
        stages=devs(1, 2, 3, 5),
    )
    add(
        "2026-11-04T10:45:00",
        MEI,
        "feat: refunds on cancellation [M04.3]",
        task="M04.3",
        paths=("src/payments/refunds.py", MIG_PAYMENTS),
    )
    add(
        "2026-11-04T11:30:00",
        NADIA,
        "docs: D004 late refunds are partial [M04.3]",
        paths=(DEVIATIONS[4],),
        stages=devs(1, 2, 3, 4, 5),
    )
    add(
        "2026-11-06T15:20:00",
        MEI,
        "test: payment checks [M04.4]",
        task="M04.4",
        paths=("tests/test_payments.py",),
    )
    add("2026-11-07T09:00:00", NADIA, "docs: close M04 [M04]", close="M04")
    # --- M05a
    add(
        "2026-11-10T11:40:00",
        MEI,
        "feat: join the waitlist [M05a.1]",
        task="M05a.1",
        paths=("src/waitlist/__init__.py", "src/waitlist/join.py", "migrations/0005_waitlist.sql"),
    )
    add(
        "2026-11-12T10:30:00",
        TOMAS,
        "feat: promote the oldest waiting entry [M05a.2]",
        task="M05a.2",
        paths=("src/waitlist/promote.py", MODEL),
    )
    add(
        "2026-11-12T11:10:00",
        NADIA,
        "docs: D006 promoted entries hold the slot [M05a.2]",
        paths=(DEVIATIONS[6],),
        stages=devs(1, 2, 3, 4, 5, 6),
    )
    add("2026-11-13T14:00:00", MEI, "test: waitlist check 1", paths=("tests/test_waitlist.py",))
    add("2026-11-14T09:20:00", TOMAS, "chore: format with ruff", paths=(CAPTURE, OVERRIDES))
    add(
        "2026-11-14T09:50:00",
        TOMAS,
        "chore: stub packages for reminders and reports",
        paths=("src/reminders/__init__.py", "src/reports/__init__.py"),
    )
    add("2026-11-14T16:30:00", NADIA, "docs: update the CLAUDE.md status block", paths=(CLAUDE,))
    return steps


def notes_free_migration(text: str, *, ends: bool, cancelled: bool) -> str:
    """The bookings migration before D002 (a duration) and D003 (no ``cancelled_at``)."""
    if not ends:
        text = text.replace(
            "    ends_at timestamptz not null,\n", "    duration_minutes int not null,\n"
        )
    if not cancelled:
        text = text.replace("    cancelled_at timestamptz,\n", "")
    return text


def booking_test_v1(text: str) -> str:
    """The booking tests before check 4 (and the cancel import it needs)."""
    text = cut_before(text, "\n\ndef test_spec03_ac4") + "\n"
    return text.replace("from booking.cancel import cancel\n", "").replace(
        "from dataclasses import replace\n", ""
    )


def unformatted_capture(text: str) -> str:
    return text.replace(
        "def capture(\n    payments: dict[str, Payment], booking_id: str, amount_cents: int, "
        "now: datetime\n) -> Payment:",
        "def capture(payments: dict[str, Payment], booking_id: str, amount_cents: int, "
        "now: datetime) -> Payment:",
    )


def unformatted_overrides(text: str) -> str:
    return text.replace(
        "    length = booking.ends_at - booking.starts_at\n"
        "    moved = replace(booking, starts_at=new_start, ends_at=new_start + length)\n",
        "    moved = replace(booking, starts_at=new_start, "
        "ends_at=new_start + (booking.ends_at - booking.starts_at))\n",
    )


# ---------------------------------------------------------------- git


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    base = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args],
        cwd=repo,
        env={**base, **(env or {})},
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8").strip()


def sample_files() -> dict[str, bytes]:
    out = {}
    for path in sorted(SAMPLE.rglob("*")):
        rel = path.relative_to(SAMPLE)
        if path.is_file() and not SKIP_DIRS & set(rel.parts) and rel.as_posix() not in SKIP_FILES:
            out[rel.as_posix()] = path.read_bytes()
    return out


def replay(repo: Path, steps: list[Step]) -> None:
    git(repo, "init", "-q", "-b", "main")
    for step in steps:
        for rel, text in step.files.items():
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        stamp = f"{step.when}+00:00"
        env = {
            "GIT_AUTHOR_NAME": step.name,
            "GIT_AUTHOR_EMAIL": step.email,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_NAME": step.name,
            "GIT_COMMITTER_EMAIL": step.email,
            "GIT_COMMITTER_DATE": stamp,
        }
        git(repo, "add", "-A", env=env)
        git(repo, "commit", "-q", "--allow-empty", "-m", step.message, env=env)


def check_tip_tree(repo: Path, expected: dict[str, bytes]) -> None:
    """The replayed tree must equal ``samples/courtside/`` (docs and code, not ``.sdd``)."""
    found = {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(repo).parts
    }
    missing, extra = sorted(set(expected) - set(found)), sorted(set(found) - set(expected))
    differ = sorted(p for p in set(found) & set(expected) if found[p] != expected[p])
    if missing or extra or differ:
        raise SystemExit(
            f"the replayed tip tree differs from samples/courtside: missing {missing}, "
            f"extra {extra}, different {differ}"
        )


# ---------------------------------------------------------------- the build


def drop_writer_markers(folder: Path) -> None:
    for marker in folder.rglob(".cypherlite.writer"):
        marker.unlink()


def main() -> None:  # noqa: PLR0915 - one numbered step after another
    if not SAMPLE.is_dir():
        raise SystemExit(f"{SAMPLE} does not exist")
    sample_settings = config.load(SAMPLE, ":memory:", env={})

    print("1. status block of samples/courtside/CLAUDE.md")
    status = commands.export_claude_status(sample_settings)
    print(f"   {status['path']} {'updated' if status['changed'] else 'already up to date'}")

    print("2. scripted history -> samples/courtside.bundle")
    expected = sample_files()
    steps = build_steps(lambda rel: expected[rel].decode("utf-8"))
    with tempfile.TemporaryDirectory(prefix="make-sample-") as tmp:
        work = Path(tmp)
        repo = work / "history"
        repo.mkdir()
        replay(repo, steps)
        check_tip_tree(repo, expected)
        BUNDLE.unlink(missing_ok=True)
        # HEAD too, so a plain `git clone` of the bundle checks out main (M06b's prepare)
        git(repo, "bundle", "create", str(BUNDLE), "HEAD", "main")
        tip = git(repo, "rev-parse", "HEAD")

        print("3. clone, sync and snapshot")
        clone = work / "courtside"
        git(work, "clone", "-q", str(BUNDLE), str(clone))
        sdd_dir = SAMPLE / ".sdd"
        live = sdd_dir / "graph"
        for old in (live, sdd_dir / "snapshots"):
            shutil.rmtree(old, ignore_errors=True)
        settings = config.load(clone, str(live), env={})
        synced = indexing.sync(settings)
        out = sdd_dir / "snapshots"
        snap = snapshot.snapshot(settings, out)
        drop_writer_markers(sdd_dir)
        graph_json = (out / "graph-json" / "graph.json").read_text(encoding="utf-8")
        leaked = [p for p in (tmp, str(clone)) if p in graph_json]

    print("4. checks")
    problems: list[str] = []
    report = indexing.doctor(sample_settings)
    sev = report["warnings_by_severity"]
    if any(sev.values()) or report["counts"]["unresolved_links"]:
        problems.append(f"doctor: {sev}, {report['counts']['unresolved_links']} unresolved")
    if leaked:
        problems.append(f"a temp path leaked into graph.json: {leaked}")
    if synced["git"] is None:
        problems.append("git sync was skipped")
    with store.Store.open(live, read_only=True) as st:
        runtime = Runtime(settings=sample_settings, store=st)
        result = impact.impact(runtime, "bookings")
    counts = result["counts"]
    empty = [g for g in EXPECTED_GROUPS if not counts[g]]
    if empty:
        problems.append(f"impact bookings: empty groups {empty}")
    if problems:
        raise SystemExit("make_sample failed:\n  " + "\n  ".join(problems))

    print("\nsummary")
    print(f"  commits         {len(steps)} (tip {tip[:7]})")
    print(f"  bundle          {BUNDLE.relative_to(ROOT)} ({BUNDLE.stat().st_size} bytes)")
    print(f"  store           {synced['nodes']} nodes, {synced['relationships']} relationships")
    print(f"  snapshot copies {snap['copies']}")
    print(f"  doctor          {sev} (0 unresolved links)")
    print("  impact bookings " + ", ".join(f"{g} {counts[g]}" for g in impact.GROUPS))


EXPECTED_GROUPS = (
    "specs",
    "sections",
    "tables",
    "features",
    "files",
    "tasks_open",
    "tasks_done",
    "deviations",
    "tests",
    "commits",
)

if __name__ == "__main__":
    sys.exit(main())
