"""The sprint replay: simulated agents working the sample in a loop (SPEC-11 §4).

One :class:`Replay` owns ``<data>/run/.sdd/graph``. Each :meth:`Replay.tick` lets the workers
``sonnet-1…3`` claim and complete tasks through the same ``service.coordination`` functions the
MCP tools use, and the orchestrator ``opus-orch`` close milestones. After every write the store is
checkpointed, so ``sdd public`` sees it on its next reopen. ``demo/`` never imports ``graph``.
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from sdd.config import Settings
from sdd.demo.prepare import prepare
from sdd.demo.script import ReplayScript
from sdd.errors import SddError
from sdd.service import coordination, progress
from sdd.service.runtime import Runtime

__all__ = ["HEARTBEAT", "ORCHESTRATOR", "WORKERS", "Replay"]

log = logging.getLogger("sdd.replay")

ORCHESTRATOR = "opus-orch"
WORKERS = ("sonnet-1", "sonnet-2", "sonnet-3")
HEARTBEAT = Path(".sdd") / "replay.heartbeat"
HEARTBEAT_EVERY = 5.0  # seconds, during any pause
RESET_PAUSE = 30.0
WORK_TICKS = (2, 5)  # a worker finishes after this many ticks (inclusive)

Sleep = Callable[[float], None]


class Replay:
    def __init__(
        self,
        settings_for: Callable[[Path], Settings],
        sample: Path,
        data: Path,
        script: ReplayScript,
        seed: int | None = None,
    ) -> None:
        self.settings_for = settings_for
        self.sample = sample
        self.data = data
        self.script = script
        self.seed = seed
        self.rng = random.Random(seed)
        self.runtime: Runtime | None = None
        self.ticks = 0
        self.task_of: dict[str, str] = {}  # worker -> task it holds
        self.left: dict[str, int] = {}  # worker -> ticks until it finishes
        # (tick, agent, action, task or milestone): the determinism test compares these
        self.actions: list[tuple[int, str, str, str]] = []
        self.started = time.monotonic()

    @property
    def run_dir(self) -> Path:
        return self.data / "run"

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Prepare ``<data>/run``, open its store, sync, checkpoint and touch the heartbeat."""
        self.runtime = self._open(prepare(self.sample, self.data))
        self._fresh()
        self.heartbeat()

    def _fresh(self) -> None:
        self.rng = random.Random(self.seed)
        self.ticks = 0
        self.task_of.clear()
        self.left.clear()
        self.started = time.monotonic()

    def _open(self, root: Path) -> Runtime:
        runtime = Runtime.open(self.settings_for(root))
        try:
            runtime.sync(full=True)
            runtime.store.checkpoint()
        except BaseException:
            runtime.close()
            raise
        return runtime

    def close(self) -> None:
        if self.runtime is not None:
            self.runtime.close()
            self.runtime = None

    def heartbeat(self, root: Path | None = None) -> None:
        path = (root or self.run_dir) / HEARTBEAT
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            os.utime(path)
        except OSError:
            log.warning("could not touch the heartbeat file")

    # ------------------------------------------------------------ one tick

    def tick(self) -> bool:
        """One tick. ``False`` once every run milestone is complete."""
        assert self.runtime is not None, "call start() first"
        if self._all_done():
            return False
        self.ticks += 1
        for worker in WORKERS:
            task = self.task_of.get(worker)
            if task is None:
                self._claim(worker)
                continue
            self.left[worker] -= 1
            if self.left[worker] <= 0:
                self._finish(worker, task)
        self._orchestrate()
        self.heartbeat()
        return not self._all_done()

    def _states(self) -> dict[str, tuple[str, int]]:
        assert self.runtime is not None
        return progress.milestone_status(self.runtime)

    def _all_done(self) -> bool:
        states = self._states()
        return all(states.get(m, ("", 1))[0] == "done" for m in self.script.milestones)

    def _write(self, agent: str, action: str, target: str, call: Callable[[], object]) -> bool:
        """Run one write call and checkpoint; a failure is logged by code and the loop goes on."""
        assert self.runtime is not None
        try:
            call()
            self.runtime.store.checkpoint()
        except SddError as exc:
            log.warning("%s %s %s failed: %s", agent, action, target, exc.code)
            self.actions.append((self.ticks, agent, f"{action}_failed:{exc.code}", target))
            return False
        self.actions.append((self.ticks, agent, action, target))
        return True

    def _claim(self, worker: str) -> None:
        assert self.runtime is not None
        runtime = self.runtime
        states = self._states()
        milestone = next(
            (m for m in self.script.milestones if states.get(m, ("", 1))[0] != "done"), None
        )
        if milestone is None:
            return
        try:
            found = coordination.next_tasks(runtime, milestone=milestone, limit=10, agent=worker)
        except SddError as exc:
            log.warning("%s next_tasks failed: %s", worker, exc.code)
            return
        if not found["tasks"]:
            return
        task = str(found["tasks"][0]["id"])
        if self._write(
            worker, "claim", task, lambda: coordination.claim_task(runtime, task, worker)
        ):
            self.task_of[worker] = task
            self.left[worker] = self.rng.randint(*WORK_TICKS)

    def _finish(self, worker: str, task: str) -> None:
        assert self.runtime is not None
        runtime = self.runtime
        scripted = self.script.deviations.get(task)
        if scripted is not None:
            self._write(
                worker,
                "deviation",
                task,
                lambda: coordination.log_deviation(
                    runtime,
                    task,
                    worker,
                    title=scripted.title,
                    spec_says=scripted.spec_says,
                    implementation_does=scripted.does,
                    why=scripted.why,
                    consequences=scripted.consequences,
                    amends=scripted.amends,
                    affects=scripted.affects,
                ),
            )
        outcome = self.script.outcomes.get(task)
        if outcome is not None and outcome.notes is not None:
            notes = outcome.notes
        else:
            refs = progress.section_refs(runtime, task)
            notes = f"Done per {', '.join(refs)}." if refs else "Done."
        files = list(outcome.files) if outcome is not None else []
        self._write(
            worker,
            "complete",
            task,
            lambda: coordination.complete_task(
                runtime, task, worker, notes=notes, files_touched=files or None
            ),
        )
        # the worker lets go either way, so one failing task never stalls the loop
        del self.task_of[worker]
        del self.left[worker]

    def _orchestrate(self) -> None:
        assert self.runtime is not None
        runtime = self.runtime
        verification = self.script.verification
        for milestone in self.script.milestones:
            status, open_tasks = self._states().get(milestone, ("", 1))
            if status == "done" or open_tasks:
                continue
            self._write(
                ORCHESTRATOR,
                "milestone_done",
                milestone,
                lambda m=milestone: coordination.complete_milestone(  # type: ignore[misc]
                    runtime, m, ORCHESTRATOR, verification
                ),
            )

    # ------------------------------------------------------------ reset

    def reset(self) -> None:
        """Swap in a fresh copy: prepare ``run.next`` first, rename late (SPEC-11 §4 step 4)."""
        nxt = self._open(prepare(self.sample, self.data, target="run.next"))
        self.heartbeat(self.data / "run.next")
        nxt.close()
        self.close()
        old = self.data / "run.old"
        if old.exists():
            shutil.rmtree(old)
        os.rename(self.run_dir, old)
        os.rename(self.data / "run.next", self.run_dir)
        shutil.rmtree(old, ignore_errors=True)
        self.runtime = self._open(self.run_dir)
        self._fresh()
        self.heartbeat()

    # ------------------------------------------------------------ the loop

    def _pause(self, seconds: float, sleep: Sleep | None, stop: threading.Event | None) -> None:
        """Wait ``seconds``, touching the heartbeat every 5 s; returns early on ``stop``."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            if stop is not None and stop.is_set():
                return
            step = min(HEARTBEAT_EVERY, left)
            if sleep is not None:
                sleep(step)
            elif stop is not None:
                stop.wait(step)
            else:
                time.sleep(step)
            self.heartbeat()

    def run(self, sleep: Sleep | None = None, stop: threading.Event | None = None) -> None:
        """Start, then tick forever; reset after the scripted milestones or ``replay_max_min``."""
        self.start()
        try:
            while stop is None or not stop.is_set():
                assert self.runtime is not None
                settings = self.runtime.settings
                more = self.tick()
                expired = time.monotonic() - self.started >= settings.replay_max_min * 60
                if not more or expired:
                    self._pause(RESET_PAUSE, sleep, stop)
                    if stop is not None and stop.is_set():
                        break
                    self.reset()
                    continue
                self._pause(settings.replay_tick, sleep, stop)
        finally:
            self.close()
