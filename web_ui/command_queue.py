from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable


class CommandBusyError(RuntimeError):
    """Raised when another command already owns the single worker."""


class CommandQueue:
    """A single in-process worker slot for all mock robot commands."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_task: asyncio.Task[None] | None = None
        self._active_job_id: str | None = None

    @property
    def busy(self) -> bool:
        return self._active_task is not None and not self._active_task.done()

    @property
    def active_job_id(self) -> str | None:
        return self._active_job_id if self.busy else None

    async def submit(
        self,
        command_name: str,
        operation: Callable[[], Awaitable[None]],
    ) -> str:
        async with self._lock:
            if self.busy:
                raise CommandBusyError("다른 작업이 실행 중입니다.")

            job_id = f"{command_name}-{uuid.uuid4().hex[:8]}"
            self._active_job_id = job_id
            self._active_task = asyncio.create_task(
                self._run(operation), name=job_id
            )
            return job_id

    async def _run(self, operation: Callable[[], Awaitable[None]]) -> None:
        try:
            result = operation()
            if not inspect.isawaitable(result):
                raise TypeError("명령 작업은 await 가능한 함수여야 합니다.")
            await result
        finally:
            async with self._lock:
                self._active_job_id = None
                self._active_task = None

    async def wait_for_idle(self, timeout: float = 3.0) -> None:
        task = self._active_task
        if task is None:
            return
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
