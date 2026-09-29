import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress


async def batch_deltas(source: AsyncIterator[str], interval: float = 0.12, max_chars: int = 160) -> AsyncIterator[str]:
    iterator = source.__aiter__()
    pending = ""
    first = True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + interval
    task = None
    try:
        while True:
            if task is None:
                task = asyncio.create_task(anext(iterator))
            timeout = max(0, deadline - loop.time()) if pending else None
            ready, _ = await asyncio.wait({task}, timeout=timeout)
            if not ready:
                yield pending
                pending = ""
                continue
            completed, task = task, None
            try:
                delta = completed.result()
            except StopAsyncIteration:
                if pending:
                    yield pending
                break
            if not delta:
                continue
            if first:
                first = False
                yield delta
                continue
            if not pending:
                deadline = loop.time() + interval
            pending += delta
            if len(pending) >= max_chars or loop.time() >= deadline:
                yield pending
                pending = ""
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await task
        close = getattr(iterator, "aclose", None)
        if close:
            await close()
