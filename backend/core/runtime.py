import asyncio
import os
from typing import Any, Callable, Coroutine


MAX_ACTIVE_PIPELINES = int(os.getenv("MAX_ACTIVE_PIPELINES", "1"))


class PipelineRunner:
    """Per-task mutex for pipeline execution with run_id isolation.

    Ensures only one pipeline runs per task_id at a time.
    Enforces a global capacity limit (MAX_ACTIVE_PIPELINES).
    Tracks run_id so stale runs can be detected and rejected.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._task_runs: dict[str, str] = {}
        self._cancelled: dict[str, asyncio.Event] = {}
        self._lock_holder: set[str] = set()

    def claim(self, task_id: str, run_id: str) -> bool:
        """Sole occupancy entry for both sync and async operations.

        Returns False if task is already occupied or global capacity is full.
        Caller must call release() when done, or must call start_claimed()
        to transition into an async pipeline (which auto-releases on completion).
        """
        if task_id in self._lock_holder:
            return False
        if len(self._lock_holder) >= MAX_ACTIVE_PIPELINES:
            return False
        self._lock_holder.add(task_id)
        self._task_runs[task_id] = run_id
        return True

    def start_claimed(self, task_id: str, run_id: str, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> bool:
        """Start an async pipeline for an already-claimed run.

        Only succeeds if task_id + run_id pair is currently claimed.
        The pipeline lifecycle ends with release() automatically.
        Returns False if the run is no longer the current claim.
        """
        if self._task_runs.get(task_id) != run_id:
            return False
        asyncio.create_task(self._run_guarded(task_id, run_id, coro_factory))
        return True

    def start(self, task_id: str, run_id: str, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> bool:
        """Compat: claim then start_claimed in one call."""
        if not self.claim(task_id, run_id):
            return False
        return self.start_claimed(task_id, run_id, coro_factory)

    async def _run_guarded(
        self, task_id: str, run_id: str, coro_factory: Callable[[], Coroutine[Any, Any, Any]]
    ) -> None:
        lock = self._locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            cancel_ev = self._cancelled.setdefault(task_id, asyncio.Event())
            cancel_ev.clear()
            pipeline = asyncio.create_task(coro_factory())
            self._tasks[(task_id, run_id)] = pipeline
            try:
                await pipeline
            except asyncio.CancelledError:
                pass
            finally:
                self._tasks.pop((task_id, run_id), None)
                self.release(task_id, run_id)
                self._cancelled.pop(task_id, None)
                self._locks.pop(task_id, None)

    def cancel(self, task_id: str, run_id: str | None = None) -> bool:
        """Signal graceful cancellation + cancel the running task. Returns True if was running."""
        if run_id:
            t = self._tasks.get((task_id, run_id))
            if t and not t.done():
                ev = self._cancelled.get(task_id)
                if ev:
                    ev.set()
                t.cancel()
                return True
            return False

        ev = self._cancelled.get(task_id)
        if ev:
            ev.set()
        # Cancel all tasks for this task_id
        cancelled = False
        for (tid, rid), t in list(self._tasks.items()):
            if tid == task_id and not t.done():
                t.cancel()
                cancelled = True
        return cancelled

    def is_running(self, task_id: str) -> bool:
        for (tid, rid), t in self._tasks.items():
            if tid == task_id and not t.done():
                return True
        return False

    def is_active(self, task_id: str) -> bool:
        """True if task has any active operation: async pipeline or sync claim."""
        return task_id in self._lock_holder

    def is_run_current(self, task_id: str, run_id: str) -> bool:
        return self._task_runs.get(task_id) == run_id

    def is_cancelled(self, task_id: str) -> bool:
        ev = self._cancelled.get(task_id)
        return ev is not None and ev.is_set()

    def is_any_running(self) -> bool:
        return bool(self._tasks)

    def has_capacity(self) -> bool:
        return len(self._lock_holder) < MAX_ACTIVE_PIPELINES

    def active_count(self) -> int:
        return len(self._lock_holder)

    def release(self, task_id: str, run_id: str | None = None) -> None:
        """Release capacity. Only clears lock_holder when run_id matches or force-release (None)."""
        if run_id is None or self._task_runs.get(task_id) == run_id:
            self._task_runs.pop(task_id, None)
            self._lock_holder.discard(task_id)


runner = PipelineRunner()

# LangGraph pool / checkpointer / app references (set during startup)
pool = None
checkpointer = None
app_auto = None
app_step = None
