"""M02.8: time one watcher poll over a generated 20 000-file tree (SPEC-04 §1).

Run it inside the dev container, so the tree lives in the Windows bind mount (``/workspace``) the
way the real project does:

    docker compose -f docker-compose.dev.yml exec dev uv run python scripts/measure_poll.py

It builds ``/workspace/_pollbench/`` (about 200 folders of 100 small files), times
``poll_once(code=True)`` five times, times ``poll_once(code=False)`` on this repo, prints the
numbers and the resulting intervals, then deletes the folder.
"""

from __future__ import annotations

import math
import shutil
import statistics
import sys
import time
from pathlib import Path

from sdd import config
from sdd.sync.watcher import Watcher

FOLDERS, FILES_PER_FOLDER, RUNS = 200, 100, 5


def build(root: Path) -> int:
    for f in range(FOLDERS):
        folder = root / f"pkg{f:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        for n in range(FILES_PER_FOLDER):
            (folder / f"mod{n:03d}.py").write_text(f"x = {n}\n", encoding="utf-8")
    return FOLDERS * FILES_PER_FOLDER


def timed(watcher: Watcher, *, code: bool, runs: int) -> list[float]:
    out = []
    for _ in range(runs):
        start = time.perf_counter()
        watcher.poll_once(code=code)
        out.append(time.perf_counter() - start)
    return out


def main() -> None:
    repo = Path.cwd()
    bench = repo / "_pollbench"
    shutil.rmtree(bench, ignore_errors=True)
    bench.mkdir()
    try:
        count = build(bench)
        watcher = Watcher(config.load(bench, config.MEMORY_STORE, env={}), lambda b: None)
        watcher.poll_once(code=True)  # warm-up and initial snapshot
        code = timed(watcher, code=True, runs=RUNS)
        own = Watcher(config.load(repo, config.MEMORY_STORE, env={}), lambda b: None)
        own.poll_once(code=True)
        sdd = timed(own, code=False, runs=RUNS)
    finally:
        shutil.rmtree(bench, ignore_errors=True)

    median_code, median_sdd = statistics.median(code), statistics.median(sdd)
    code_interval = max(10, math.ceil(10 * median_code))
    sdd_interval = 1.0 if median_sdd <= 0.05 else math.ceil(median_sdd * 20) / 10
    print(f"tree: {count} files in {FOLDERS} folders, {bench}")
    print(f"code poll  (20k files): min {min(code):.3f}s  median {median_code:.3f}s")
    print(f"sdd poll   (this repo): min {min(sdd):.4f}s  median {median_sdd:.4f}s")
    print(f"code poll backs off to: {code_interval} s on this tree (minimum 10 s)")
    print(f"SDD_POLL_INTERVAL default: {sdd_interval} s")
    print(f"python {sys.version.split()[0]}", file=sys.stderr)


if __name__ == "__main__":
    main()
