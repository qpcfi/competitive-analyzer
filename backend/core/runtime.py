import asyncio
from typing import Any, Callable, Coroutine


class PipelineRunner:
    """Per-task mutex for pipeline execution.

    Ensures only one pipeline runs per task_id at a time.
    Provides graceful cancellation signal that pipelines can poll between phases.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancelled: dict[str, asyncio.Event] = {}
        self._lock_holder: set[str] = set()

    def start(
        self, task_id: str, coro_factory: Callable[[], Coroutine[Any, Any, Any]]
    ) -> bool:
        """Fire-and-forget. Returns False if a pipeline is already committed or running."""
        if task_id in self._lock_holder:
            return False
        self._lock_holder.add(task_id)
        asyncio.create_task(self._run_guarded(task_id, coro_factory))
        return True

    async def _run_guarded(
        self, task_id: str, coro_factory: Callable[[], Coroutine[Any, Any, Any]]
    ) -> None:
        lock = self._locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            cancel_ev = self._cancelled.setdefault(task_id, asyncio.Event())
            cancel_ev.clear()
            pipeline = asyncio.create_task(coro_factory())
            self._tasks[task_id] = pipeline
            try:
                await pipeline
            except asyncio.CancelledError:
                pass
            finally:
                self._tasks.pop(task_id, None)
                self._cancelled.pop(task_id, None)
                self._locks.pop(task_id, None)
                self._lock_holder.discard(task_id)

    def cancel(self, task_id: str) -> bool:
        """Signal graceful cancellation + cancel the running task. Returns True if was running."""
        ev = self._cancelled.get(task_id)
        if ev:
            ev.set()
        t = self._tasks.get(task_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    def is_running(self, task_id: str) -> bool:
        t = self._tasks.get(task_id)
        return t is not None and not t.done()

    def is_cancelled(self, task_id: str) -> bool:
        ev = self._cancelled.get(task_id)
        return ev is not None and ev.is_set()

    def is_any_running(self) -> bool:
        return bool(self._tasks)


runner = PipelineRunner()

# LangGraph pool / checkpointer / app references (set during startup)
pool = None
checkpointer = None
app_auto = None
app_step = None
