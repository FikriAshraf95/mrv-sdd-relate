"""``sdd bench`` (SPEC-10 §5): what the graph saves, measured on a copy of a project.

Every bench works on a **copy** of the project in a temporary folder (without ``.sdd`` and
``.git``) with its own freshly built store, so the project and its committed store are never
touched. Sizes are characters; estimated tokens are chars ÷ 4 (rounded up). ``--exact`` asks the
Anthropic token-counting API instead (``ANTHROPIC_API_KEY`` in the environment; never in tests).
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdd import config
from sdd.errors import SddError
from sdd.service import changes, context, coordination
from sdd.service.runtime import Runtime

__all__ = [
    "bench_collisions",
    "bench_context",
    "bench_restart",
    "render_markdown",
    "tokens_est",
    "write_results",
]

COPY_SKIP = {".sdd", ".git", "__pycache__", ".pytest_cache"}
COUNT_URL = "https://api.anthropic.com/v1/messages/count_tokens"
COUNT_MODEL = "claude-sonnet-5-5"
BENCH_AGENT = "bench"


def tokens_est(chars: int) -> int:
    return math.ceil(chars / 4)


# ---------------------------------------------------------------- a working copy


@contextmanager
def _copy(project: Path) -> Iterator[Runtime]:
    """A writable runtime on a full sync of a copy of ``project``."""
    with tempfile.TemporaryDirectory(prefix="sdd-bench-") as tmp:
        root = Path(tmp) / "project"
        shutil.copytree(project, root, ignore=shutil.ignore_patterns(*COPY_SKIP))
        settings = config.load(root, str(root / ".sdd" / "graph"))
        runtime = Runtime.open(settings)
        try:
            runtime.sync(full=True)
            yield runtime
        finally:
            runtime.close()


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def _count_exact(texts: list[str]) -> list[int]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SddError("invalid_input", "--exact needs ANTHROPIC_API_KEY in the environment.")
    out: list[int] = []
    for text in texts:
        body = json.dumps(
            {"model": COUNT_MODEL, "messages": [{"role": "user", "content": text or " "}]}
        ).encode()
        req = urllib.request.Request(
            COUNT_URL,
            data=body,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                out.append(int(json.load(resp)["input_tokens"]))
        except (urllib.error.URLError, KeyError, ValueError) as err:
            raise SddError("invalid_input", f"token counting failed: {type(err).__name__}") from err
    return out


# ---------------------------------------------------------------- 5.1 context per task


@dataclass(slots=True)
class _Baseline:
    """The Markdown an agent reads for one task by the token rule, file by file."""

    parts: dict[str, str] = field(default_factory=dict)  # label → text, in reading order

    def add(self, label: str, text: str) -> None:
        self.parts.setdefault(label, text)

    @property
    def text(self) -> str:
        return "\n".join(self.parts.values())


def _lines(text: str, start: int, end: int) -> str:
    return "".join(text.splitlines(keepends=True)[start - 1 : end])


def _baseline(runtime: Runtime, task_id: str, milestone: dict[str, Any]) -> _Baseline:
    """CLAUDE.md, the whole milestone file, each *Read first* target (the whole file when marked,
    else the section line ranges plus the ``grep -n '^## '`` output), DEVIATIONS.md, every
    deviation file amending a section read, and the plan file when there is one."""
    root, store = runtime.settings.project_root, runtime.store
    b = _Baseline()
    b.add("CLAUDE.md", _read(root, "CLAUDE.md"))
    b.add(str(milestone["path"]), _read(root, str(milestone["path"])))
    mid = str(milestone["id"])
    read_sections: set[str] = set()
    for r in store.read(
        "MATCH (m:Milestone {id: $id})-[e:READS]->(x) RETURN x.id AS id, labels(x) AS labels, "
        "e.whole AS whole",
        {"id": mid},
    ):
        target = str(r["id"])
        if "Spec" in (r["labels"] or []) or "#" not in target:
            spec = store.read("MATCH (s:Spec {id: $id}) RETURN s.source_path AS p", {"id": target})
            if spec:
                path = str(spec[0]["p"])
                b.add(path, _read(root, path))
                read_sections.update(
                    str(s["id"])
                    for s in store.read(
                        "MATCH (s:Section) WHERE s.spec_id = $id RETURN s.id AS id", {"id": target}
                    )
                )
            continue
        # a section, with its descendants: one contiguous line range of the file
        rows = store.read(
            "MATCH (s:Section {id: $id}) OPTIONAL MATCH (s)-[:HAS_SECTION*0..4]->(d:Section) "
            "RETURN s.source_path AS p, s.spec_id AS spec, min(d.line_start) AS a, "
            "max(d.line_end) AS z, collect(d.id) AS ids",
            {"id": target},
        )
        if not rows or rows[0]["p"] is None:
            continue
        row = rows[0]
        path = str(row["p"])
        text = _read(root, path)
        heads = "\n".join(
            line for line in text.splitlines() if re.match(r"^## ", line)
        )  # the grep -n '^## ' step, cost counted once per file
        b.add(f"grep {path}", heads)
        b.add(f"{path}:{row['a']}-{row['z']}", _lines(text, int(row["a"]), int(row["z"])))
        read_sections.update(str(i) for i in row["ids"] or [])
    for r in store.read(
        "MATCH (d:Deviation)-[:AMENDS]->(x) RETURN d.id AS id, d.source_path AS p, x.id AS x"
    ):
        if str(r["x"]) in read_sections or str(r["x"]) in b.parts:
            b.add(str(r["p"]), _read(root, str(r["p"])))
    b.add("docs/DEVIATIONS.md", _read(root, "docs/DEVIATIONS.md"))
    for r in store.read(
        "MATCH (p:Doc)-[:PLANS]->(m:Milestone {id: $id}) RETURN p.path AS p", {"id": mid}
    ):
        b.add(str(r["p"]), _read(root, str(r["p"])))
    return b


def bench_context(
    project: Path, milestones: list[str] | None = None, *, exact: bool = False
) -> dict[str, Any]:
    """The three variants per task (SPEC-10 §5.1) and their averages."""
    wanted = {coordination.milestone_ident(m) for m in milestones or []}
    rows: list[dict[str, Any]] = []
    texts: list[str] = []
    with _copy(project) as runtime:
        ms = {
            str(m["id"]): m
            for m in runtime.store.read(
                "MATCH (m:Milestone) RETURN m.id AS id, m.path AS path, m.order AS ord ORDER BY ord"
            )
        }
        tasks = runtime.store.read(
            "MATCH (t:Task) RETURN t.id AS id, t.milestone_id AS m, t.order AS ord ORDER BY m, ord"
        )
        for t in tasks:
            mid = str(t["m"])
            if mid not in ms or (wanted and mid not in wanted):
                continue
            tid = str(t["id"])
            base = _baseline(runtime, tid, ms[mid])
            pk_task = context.get_context(runtime, tid, "task", 1_000_000)
            pk_ms = context.get_context(runtime, tid, "milestone", 1_000_000)
            rows.append(
                {
                    "task": tid,
                    "markdown_chars": len(base.text),
                    "milestone_chars": pk_ms["size"]["chars"],
                    "task_chars": pk_task["size"]["chars"],
                }
            )
            texts += [
                base.text,
                json.dumps(pk_ms, ensure_ascii=False),
                json.dumps(pk_task, ensure_ascii=False),
            ]
    if not rows:
        raise SddError("invalid_input", "No tasks to measure (check --milestone).")
    if exact:
        counts = _count_exact(texts)
        for i, row in enumerate(rows):
            row["markdown_tokens"], row["milestone_tokens"], row["task_tokens"] = counts[
                3 * i : 3 * i + 3
            ]
    else:
        for row in rows:
            for key in ("markdown", "milestone", "task"):
                row[f"{key}_tokens"] = tokens_est(row[f"{key}_chars"])
    n = len(rows)
    avg = {
        k: round(sum(r[k] for r in rows) / n, 1)
        for k in rows[0]
        if k != "task" and isinstance(rows[0][k], int)
    }
    return {
        "bench": "context",
        "tokens": "exact" if exact else "chars/4",
        "tasks": n,
        "rows": rows,
        "average": avg,
        "saving_task_pct": round(100 * (1 - avg["task_chars"] / avg["markdown_chars"]), 1),
        "saving_milestone_pct": round(
            100 * (1 - avg["milestone_chars"] / avg["markdown_chars"]), 1
        ),
    }


# ---------------------------------------------------------------- 5.2 session restart


def _append_to_section(root: Path, spec_id: str, number: str, sentence: str) -> str:
    """Add a sentence to the last line of a numbered section's body; returns the file path."""
    path = next(p for p in (root / "docs" / "specs").glob(f"{spec_id}-*.md"))
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    heading = next(
        i for i, ln in enumerate(lines) if re.match(rf"^##+ {re.escape(number)}\.? ", ln)
    )
    body = next(i for i in range(heading + 1, len(lines)) if lines[i].strip())
    lines[body] = lines[body].rstrip("\n") + f" {sentence}\n"
    path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return path.relative_to(root).as_posix()


def bench_restart(project: Path, *, exact: bool = False) -> dict[str, Any]:
    """ "What changed since my last session?" after two section edits, one deviation and three
    completed tasks (SPEC-10 §5.2)."""
    with _copy(project) as runtime:
        root = runtime.settings.project_root
        changes.what_changed(runtime, "last_session", BENCH_AGENT)  # the last session ends here
        time.sleep(1.1)  # one-second event resolution: later events fall strictly after
        specs = [
            str(r["id"])
            for r in runtime.store.read("MATCH (s:Spec) RETURN s.id AS id ORDER BY id")
            if str(r["id"]) != "SPEC-00"
        ]
        edited: list[str] = []
        for spec_id in specs[:2]:
            sec = runtime.store.read(
                "MATCH (s:Section) WHERE s.spec_id = $id AND s.number IS NOT NULL "
                "RETURN s.number AS n ORDER BY s.line_start LIMIT 1",
                {"id": spec_id},
            )
            edited.append(
                _append_to_section(root, spec_id, str(sec[0]["n"]), "(Reworded for the bench.)")
            )
        runtime.sync(full=True)
        ids: list[str] = []
        for _ in range(3):  # one at a time: finishing a task can unblock the next
            picked = coordination.next_tasks(runtime, limit=1, agent=BENCH_AGENT)["tasks"]
            if not picked and ids:  # the milestone is finished: close it to open the next one
                coordination.complete_milestone(
                    runtime, ids[-1].split(".")[0], BENCH_AGENT, "closed by the bench"
                )
                picked = coordination.next_tasks(runtime, limit=1, agent=BENCH_AGENT)["tasks"]
            if not picked:
                raise SddError("invalid_input", "The project needs three tasks to complete.")
            tid = str(picked[0]["id"])
            coordination.claim_task(runtime, tid, BENCH_AGENT)
            ids.append(tid)
            if len(ids) == 1:
                coordination.log_deviation(
                    runtime,
                    tid,
                    BENCH_AGENT,
                    title="Bench deviation",
                    spec_says="The scripted edit set has one deviation.",
                    implementation_does="The bench logs it.",
                    why="To measure a session restart.",
                    amends=[f"{specs[0]} §1"],
                )
            coordination.complete_task(runtime, tid, BENCH_AGENT, notes="done by the bench")
        result = changes.what_changed(runtime, "last_session", BENCH_AGENT)
        graph_text = json.dumps(result, ensure_ascii=False)

        # baseline: CLAUDE.md, the active milestone, DEVIATIONS.md and every file changed since
        names = {"CLAUDE.md", "docs/DEVIATIONS.md", *edited}
        for r in runtime.store.read(
            "MATCH (t:Task) WHERE t.id IN $ids RETURN DISTINCT t.milestone_id AS m", {"ids": ids}
        ):
            for m in runtime.store.read(
                "MATCH (m:Milestone {id: $id}) RETURN m.path AS p", {"id": r["m"]}
            ):
                names.add(str(m["p"]))
        names.update(
            str(r["p"])
            for r in runtime.store.read(
                "MATCH (d:Deviation {title: 'Bench deviation'}) RETURN d.source_path AS p"
            )
        )
        base_text = "\n".join(_read(root, n) for n in sorted(names))
        graph_chars, base_chars = len(graph_text), len(base_text)
        if exact:
            base_tokens, graph_tokens = _count_exact([base_text, graph_text])
        else:
            base_tokens, graph_tokens = tokens_est(base_chars), tokens_est(graph_chars)
    return {
        "bench": "restart",
        "tokens": "exact" if exact else "chars/4",
        "edits": {"sections": len(edited), "deviations": 1, "tasks_completed": len(ids)},
        "baseline_files": sorted(names),
        "markdown_chars": base_chars,
        "graph_chars": graph_chars,
        "markdown_tokens": base_tokens,
        "graph_tokens": graph_tokens,
        "saving_pct": round(100 * (1 - graph_chars / base_chars), 1),
    }


# ---------------------------------------------------------------- 5.3 parallel collisions

_BENCH_SPEC = """# SPEC-01 — Bench

> **Spec ID:** SPEC-01

## 1. Counter
Nothing here but a section.
"""


def _bench_project(root: Path, tasks: int) -> Path:
    (root / "docs" / "specs").mkdir(parents=True)
    (root / "docs" / "milestones").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("# Bench\n", encoding="utf-8")
    (root / "docs" / "specs" / "SPEC-01-bench.md").write_text(_BENCH_SPEC, encoding="utf-8")
    lines = [
        "# M01 — Collisions",
        "",
        "> **Read first:** [SPEC-01 §1](../specs/SPEC-01-bench.md#1-counter)",
        "",
        "## Goal",
        "Tick every box.",
        "",
        "## Tasks",
        *(
            f"- [ ] **M01.{i}** Task {i} ([SPEC-01 §1](../specs/SPEC-01-bench.md#1-counter))"
            for i in range(1, tasks + 1)
        ),
        "",
        "## Acceptance criteria",
        "1. All ticked.",
        "",
        "**Status:**",
        "",
    ]
    path = root / "docs" / "milestones" / "M01-collisions.md"
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def _ticked(path: Path) -> int:
    return len(re.findall(r"^- \[x\] ", path.read_text(encoding="utf-8"), re.M))


def _naive(path: Path, agents: int, tasks: int, rng: random.Random) -> int:
    """Each agent ticks its own boxes by read-modify-write of the same file; returns lost ticks."""
    delays = [[rng.uniform(0.001, 0.006) for _ in range(tasks)] for _ in range(agents)]

    def work(agent: int) -> None:
        for k, i in enumerate(range(agent + 1, tasks + 1, agents)):
            text = path.read_text(encoding="utf-8")
            time.sleep(delays[agent][k])  # the agent "decides" between reading and writing
            path.write_text(
                text.replace(f"- [ ] **M01.{i}**", f"- [x] **M01.{i}**"), encoding="utf-8"
            )

    threads = [threading.Thread(target=work, args=(a,)) for a in range(agents)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return tasks - _ticked(path)


def _graph(root: Path, agents: int, tasks: int) -> dict[str, int]:
    """The same agents through claim_task / complete_task: double claims and lost ticks."""
    settings = config.load(root, str(root / ".sdd" / "graph"))
    runtime = Runtime.open(settings)
    try:
        runtime.sync(full=True)
        lock = threading.Lock()
        won: dict[str, list[str]] = {}
        errors: list[str] = []

        def work(agent: str) -> None:
            try:
                while True:
                    ready = coordination.next_tasks(runtime, limit=tasks, agent=agent)["tasks"]
                    if not ready:
                        return
                    for t in ready:
                        tid = str(t["id"])
                        try:
                            coordination.claim_task(runtime, tid, agent)
                        except SddError as err:
                            if err.code in ("already_claimed", "task_done"):
                                continue
                            raise
                        with lock:
                            won.setdefault(tid, []).append(agent)
                        coordination.complete_task(runtime, tid, agent)
                        break
                    else:
                        return
            except Exception as err:
                errors.append(f"{type(err).__name__}: {err}")

        threads = [threading.Thread(target=work, args=(f"agent-{a + 1}",)) for a in range(agents)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            raise SddError("invalid_input", f"graph agents failed: {errors[0]}")
        path = root / "docs" / "milestones" / "M01-collisions.md"
        return {
            "double_claims": sum(len(a) - 1 for a in won.values()),
            "lost_ticks": tasks - _ticked(path),
        }
    finally:
        runtime.close()


def bench_collisions(
    agents: int = 10, tasks: int = 30, runs: int = 5, seed: int = 7
) -> dict[str, Any]:
    """Naive read-modify-write against the graph's claims, ``runs`` times (SPEC-10 §5.3)."""
    if agents < 2 or tasks < agents or runs < 1:
        raise SddError("invalid_input", "Use --agents ≥ 2, --tasks ≥ --agents and --runs ≥ 1.")
    rng = random.Random(seed)
    results: list[dict[str, Any]] = []
    for n in range(1, runs + 1):
        with tempfile.TemporaryDirectory(prefix="sdd-bench-") as tmp:
            naive_root, graph_root = Path(tmp) / "naive", Path(tmp) / "graph"
            naive_path = _bench_project(naive_root, tasks)
            _bench_project(graph_root, tasks)
            lost = _naive(naive_path, agents, tasks, rng)
            graph = _graph(graph_root, agents, tasks)
        results.append(
            {"run": n, "naive_lost_ticks": lost, **{f"graph_{k}": v for k, v in graph.items()}}
        )
    return {
        "bench": "collisions",
        "agents": agents,
        "tasks": tasks,
        "runs": results,
        "naive_lost_ticks_total": sum(r["naive_lost_ticks"] for r in results),
        "graph_double_claims_total": sum(r["graph_double_claims"] for r in results),
        "graph_lost_ticks_total": sum(r["graph_lost_ticks"] for r in results),
    }


# ---------------------------------------------------------------- results


def render_markdown(results: dict[str, dict[str, Any]], date: str) -> str:
    """The README table draft for whatever benches ran."""
    out = [f"# Benchmark {date}", ""]
    if (c := results.get("context")) is not None:
        a = c["average"]
        out += [
            f"## Context per task ({c['tasks']} tasks, tokens {c['tokens']})",
            "",
            "| Variant | Avg chars | Avg tokens | vs Markdown |",
            "|---|---:|---:|---:|",
            f"| Markdown (token rule) | {a['markdown_chars']:.0f} | {a['markdown_tokens']:.0f} | |",
            f"| Graph, `detail=milestone` | {a['milestone_chars']:.0f} "
            f"| {a['milestone_tokens']:.0f}"
            f" | -{c['saving_milestone_pct']}% |",
            f"| Graph, `detail=task` | {a['task_chars']:.0f} | {a['task_tokens']:.0f}"
            f" | -{c['saving_task_pct']}% |",
            "",
            "| Task | Markdown | Milestone | Task |",
            "|---|---:|---:|---:|",
            *(
                f"| {r['task']} | {r['markdown_chars']} | {r['milestone_chars']} "
                f"| {r['task_chars']} |"
                for r in c["rows"]
            ),
            "",
        ]
    if (r := results.get("restart")) is not None:
        e = r["edits"]
        out += [
            f"## Session restart (tokens {r['tokens']})",
            "",
            f"After {e['sections']} section edits, {e['deviations']} deviation and "
            f"{e['tasks_completed']} completed tasks:",
            "",
            "| Variant | Chars | Tokens |",
            "|---|---:|---:|",
            f"| Re-read Markdown ({len(r['baseline_files'])} files) | {r['markdown_chars']}"
            f" | {r['markdown_tokens']} |",
            f"| One `what_changed` | {r['graph_chars']} | {r['graph_tokens']} |",
            "",
            f"Saving: {r['saving_pct']}%.",
            "",
        ]
    if (k := results.get("collisions")) is not None:
        out += [
            f"## Parallel collisions ({k['agents']} agents, {k['tasks']} tasks, "
            f"{len(k['runs'])} runs)",
            "",
            "| Run | Naive lost ticks | Graph double claims | Graph lost ticks |",
            "|---:|---:|---:|---:|",
            *(
                f"| {r['run']} | {r['naive_lost_ticks']} | {r['graph_double_claims']}"
                f" | {r['graph_lost_ticks']} |"
                for r in k["runs"]
            ),
            f"| **total** | {k['naive_lost_ticks_total']} | {k['graph_double_claims_total']}"
            f" | {k['graph_lost_ticks_total']} |",
            "",
        ]
    return "\n".join(out)


def write_results(
    results: dict[str, dict[str, Any]], out_dir: Path, date: str
) -> tuple[Path, Path]:
    """``<out_dir>/<date>.json`` and ``.md`` (SPEC-10 §5)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    js, md = out_dir / f"{date}.json", out_dir / f"{date}.md"
    if js.is_file():  # benches run one at a time add to the day's file
        with suppress(ValueError):
            results = {**json.loads(js.read_text("utf-8")), **results}
    js.write_text(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")
    md.write_text(render_markdown(results, date), encoding="utf-8", newline="\n")
    return js, md
