"""``sdd site``: build the static demo folder from the sample (SPEC-11 §6, SPEC-08 §3).

Opens the sample's committed store read-only, calls the same service functions the HTTP routes
call, and writes their JSON under ``<out>/data/`` next to a copy of the dashboard. A top-level
wiring module like :mod:`sdd.public` (it joins ``service``, ``demo`` and ``web``, which
``service`` may not import). Nothing here reads the network or the clock: two builds over one
store are byte-identical.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from sdd import config
from sdd.demo import prepare as prepare_module
from sdd.demo.replay import Replay
from sdd.errors import SddError
from sdd.service import api_views, changes, exports, impact, query_guard
from sdd.service.runtime import Runtime
from sdd.web.api import STATIC_DIR

__all__ = ["MAX_DATA_BYTES", "WASM_FILES", "build_site"]

MANIFEST = "data/manifest.json"
MAX_DATA_BYTES = 15 * 1024 * 1024
MAX_REPLAY_TICKS = 2000
META_TAG = '<meta name="sdd-backend" content="static">'
# the files the browser needs from the @relate/relate-wasm package (snippets/ is optional)
WASM_FILES = ("relate.js", "relate_bg.wasm", "trap.js")
WASM_EXTRA = ("snippets", "LICENSE", "LICENSE.md", "README.md", "package.json")
TARGET_LABELS = ("Table", "Feature", "File", "Section")


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


class _Kind:
    """One folder of answers: ``n<counter>.json`` assigned in sorted-key order, looked up through
    ``index.json`` so that no ID ever becomes a path (IDs hold ``#``, ``/``, ``:`` and ``§``)."""

    def __init__(self, root: Path, name: str) -> None:
        self.root = root / name
        self.name = name
        self.index: dict[str, str] = {}
        self.pending: dict[str, Callable[[], Any]] = {}

    def add(self, key: str, make: Callable[[], Any]) -> None:
        self.pending[key] = make

    def write(self) -> int:
        count = 0
        for key in sorted(self.pending):
            try:
                value = self.pending[key]()
            except SddError:
                continue  # an error is not an answer: the adapter reports its own
            file = f"n{count}.json"
            _dump(self.root / file, value)
            self.index[key] = file
            count += 1
        return count


def _norm(cypher: str) -> str:
    return " ".join(cypher.split())


def _safe_out(out: Path) -> Path:
    """Refuse an ``out`` that is the repository root, ``src/`` or a folder of something else."""
    resolved = out.resolve()
    here = Path.cwd().resolve()
    if resolved in (here, *here.parents) or resolved.name in ("src", ".git"):
        raise SddError("invalid_input", f"Refusing to write the site into {out}.")
    if (resolved / "pyproject.toml").exists() or (resolved / ".git").exists():
        raise SddError("invalid_input", f"{out} looks like a project folder, not a site.")
    if resolved.exists():
        if not resolved.is_dir():
            raise SddError("invalid_input", f"{out} is not a folder.")
        if any(resolved.iterdir()) and not (resolved / MANIFEST).is_file():
            raise SddError(
                "invalid_input",
                f"{out} is not empty and is not a previous site (no {MANIFEST}).",
            )
    return resolved


def _copy_wasm(wasm_dir: Path, out: Path) -> None:
    missing = [name for name in WASM_FILES if not (wasm_dir / name).is_file()]
    if missing:
        raise SddError("invalid_input", f"--wasm-dir {wasm_dir} lacks {', '.join(missing)}.")
    target = out / "wasm"
    target.mkdir(parents=True)
    for name in (*WASM_FILES, *WASM_EXTRA):
        src = wasm_dir / name
        if src.is_dir():
            shutil.copytree(src, target / name)
        elif src.is_file():
            shutil.copy2(src, target / name)


def _index_html(static: Path) -> str:
    text = (static / "index.html").read_text(encoding="utf-8")
    anchor = re.search(r'<meta name="viewport"[^>]*>', text)
    if anchor is None:
        raise SddError("invalid_input", "index.html has no viewport meta to insert after.")
    return text[: anchor.end()] + "\n" + META_TAG + text[anchor.end() :]


def _open(sample: Path) -> Runtime:
    store = sample / ".sdd" / "graph"
    if not store.is_dir():
        raise SddError("invalid_input", f"The sample has no built store at {store}.")
    settings = config.load(sample, str(store), env={})
    return Runtime.open_public(settings)


def _record_replay(sample: Path, seed: int, synced_at: str | None) -> dict[str, Any]:
    """Run the simulated agents on a temporary copy and keep what they did, tick by tick."""
    script = prepare_module.script_for(sample)
    with tempfile.TemporaryDirectory(prefix="sdd-site-") as tmp:
        replay = Replay(
            lambda root: config.load(root, None, env={"SDD_WATCH": "poll"}),
            sample,
            Path(tmp) / "data",
            script,
            seed,
        )
        try:
            replay.start()
            assert replay.runtime is not None
            # the copy was synced just now: stamp the boards with the sample's time, not the clock
            start = {
                m: {**api_views.board(replay.runtime, m), "synced_at": synced_at}
                for m in script.milestones
            }
            ticks = 0
            while replay.tick():
                ticks += 1
                if ticks >= MAX_REPLAY_TICKS:
                    raise SddError("invalid_input", f"The replay did not finish in {ticks} ticks.")
            runtime = replay.runtime
            # every deviation the replay logged, by the task it was raised on (service, no Cypher)
            changed = changes.what_changed(runtime, since="1970-01-01T00:00:00Z")
            logged = {
                str(d["task"]): (str(d["id"]), str(d["title"])) for d in changed["deviations"]
            }
            actions = list(replay.actions)
        finally:
            replay.close()
    events: list[dict[str, Any]] = []
    for tick, agent, action, target in actions:
        if action == "claim":
            data = {
                "id": target,
                "status": "claimed",
                "claimed_by": agent,
                "milestone_id": target.split(".")[0],
            }
            events.append({"tick": tick, "type": "task", "data": data})
        elif action == "complete":
            data = {
                "id": target,
                "status": "done",
                "claimed_by": agent,
                "completed_by": agent,
                "milestone_id": target.split(".")[0],
            }
            events.append({"tick": tick, "type": "task", "data": data})
        elif action == "deviation" and target in logged:
            dev_id, title = logged[target]
            events.append(
                {"tick": tick, "type": "deviation", "data": {"id": dev_id, "title": title}}
            )
        elif action == "milestone_done":
            events.append(
                {"tick": tick, "type": "milestone", "data": {"id": target, "status": "done"}}
            )
    return {"seed": seed, "start": start, "events": events}


def build_site(  # noqa: PLR0915 - one linear build, one step per output file
    sample: Path,
    out: Path,
    *,
    wasm_dir: Path | None = None,
    seed: int = 1,
    static_dir: Path = STATIC_DIR,
) -> dict[str, Any]:
    """Write the static site and return ``{out, backend_files, answers, nodes, relationships,
    replay_events}``."""
    sample = sample.resolve()
    out = _safe_out(out)
    if wasm_dir is not None:
        missing = [n for n in WASM_FILES if not (wasm_dir / n).is_file()]
        if missing:  # before anything is deleted
            raise SddError("invalid_input", f"--wasm-dir {wasm_dir} lacks {', '.join(missing)}.")
    runtime = _open(sample)
    try:
        graph_json = exports.export_json(runtime)
        graph_cypher = exports.export_cypher(runtime)
        graph = json.loads(graph_json)
        nodes, edges = graph["nodes"], graph["edges"]

        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(static_dir, out, ignore=shutil.ignore_patterns("__pycache__"))
        (out / "index.html").write_text(_index_html(static_dir), encoding="utf-8", newline="\n")
        (out / ".nojekyll").write_text("", encoding="utf-8")
        has_wasm = wasm_dir is not None
        if wasm_dir is not None:
            _copy_wasm(wasm_dir, out)

        data = out / "data"
        data.mkdir()
        (data / "graph.json").write_text(graph_json, encoding="utf-8", newline="\n")
        (data / "graph.cypher").write_text(graph_cypher, encoding="utf-8", newline="\n")

        health = api_views.health(runtime)
        health.update(
            {"mode": "static", "instance": "static", "public_query": "presets", "base_url": None}
        )
        milestones = api_views.milestones(runtime)
        _dump(data / "health.json", health)
        _dump(data / "milestones.json", milestones)
        _dump(data / "presets.json", impact.presets())

        ids = {label: [n["id"] for n in nodes if n["label"] == label] for label in TARGET_LABELS}
        targets = [i for label in TARGET_LABELS for i in ids[label]]
        file_paths = [str(n["props"]["path"]) for n in nodes if n["label"] == "File"]
        amended = sorted({e["target"] for e in edges if e["type"] == "AMENDS"})

        kinds = {
            name: _Kind(data, name) for name in ("board", "impact", "explain", "preset", "query")
        }
        kinds["board"].add("default", partial(api_views.board, runtime))
        for m in milestones:
            kinds["board"].add(m["id"], partial(api_views.board, runtime, m["id"]))
        for t in targets:
            kinds["impact"].add(t, partial(impact.impact, runtime, t, 3))
            kinds["preset"].add(f"impact:{t}", partial(impact.preset, runtime, f"impact:{t}"))
        for p in file_paths:
            kinds["explain"].add(p, partial(impact.explain, runtime, p))
            kinds["preset"].add(f"explain:{p}", partial(impact.preset, runtime, f"explain:{p}"))
        preset_names = ["schema"]
        preset_names += [f"milestone:{m['id']}" for m in milestones]
        preset_names += [f"lineage:{s}" for s in amended]
        preset_names += [f"feature:{f.removeprefix('feature:')}" for f in ids["Feature"]]
        for name in preset_names:
            kinds["preset"].add(name, partial(impact.preset, runtime, name))
        examples = json.loads((static_dir / "examples.json").read_text(encoding="utf-8"))
        for _title, cypher in examples:
            kinds["query"].add(_norm(cypher), partial(query_guard.run_query, runtime, cypher))

        answers = sum(kind.write() for kind in kinds.values())
        index = {name: kind.index for name, kind in kinds.items()}
        _dump(data / "index.json", index)

        replay = _record_replay(sample, seed, health["synced_at"])
        _dump(data / "replay.json", replay)

        counts = {"nodes": len(nodes), "relationships": len(edges)}
        manifest = {
            "project": health["project"],
            "generated_at": health["synced_at"],
            "schema_version": health["schema_version"],
            "counts": counts,
            "centrepiece": "table:bookings",
            "wasm": has_wasm,
            "files": {"graph": "graph.json", "cypher": "graph.cypher", "replay": "replay.json"},
        }
        _dump(data / "manifest.json", manifest)
    finally:
        runtime.close()

    size = sum(p.stat().st_size for p in data.rglob("*") if p.is_file())
    if size > MAX_DATA_BYTES:
        raise SddError(
            "invalid_input",
            f"data/ is {size / 1e6:.1f} MB, over the {MAX_DATA_BYTES // 1024 // 1024} MB guard.",
        )
    return {
        "out": str(out),
        "backend_files": {"wasm": has_wasm},
        "answers": answers,
        "nodes": counts["nodes"],
        "relationships": counts["relationships"],
        "replay_events": len(replay["events"]),
        "data_bytes": size,
    }
