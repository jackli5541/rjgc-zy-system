import asyncio

from app.modules.ai_teacher.streaming import batch_deltas


def test_batch_first_and_timer_before_upstream_completes():
    async def run():
        resume = asyncio.Event()
        closed = asyncio.Event()

        async def source():
            try:
                yield "首段"
                yield "短段😀"
                await resume.wait()
                yield "末尾"
            finally:
                closed.set()

        stream = batch_deltas(source(), interval=0.01)
        assert await anext(stream) == "首段"
        assert await asyncio.wait_for(anext(stream), 0.5) == "短段😀"
        assert not closed.is_set()
        resume.set()
        assert [item async for item in stream] == ["末尾"]
        assert closed.is_set()

    asyncio.run(run())


def test_batch_cancellation_closes_upstream():
    async def run():
        closed = asyncio.Event()

        async def source():
            try:
                yield "首段"
                yield "短段"
                await asyncio.Event().wait()
            finally:
                closed.set()

        stream = batch_deltas(source(), interval=0.01)
        assert await anext(stream) == "首段"
        assert await anext(stream) == "短段"
        await stream.aclose()
        assert closed.is_set()

    asyncio.run(run())


def test_batch_propagates_upstream_error():
    async def run():
        async def source():
            yield "首段"
            raise RuntimeError("上游中断")

        stream = batch_deltas(source())
        assert await anext(stream) == "首段"
        try:
            await anext(stream)
        except RuntimeError as exc:
            assert str(exc) == "上游中断"
        else:
            raise AssertionError("Expected upstream error")

    asyncio.run(run())


def test_batch_size_limit_preserves_all_text():
    async def run():
        async def source():
            for text in ["首", "你好", "😀", "末尾"]:
                yield text

        chunks = [item async for item in batch_deltas(source(), max_chars=3)]
        assert chunks == ["首", "你好😀", "末尾"]
        assert "".join(chunks) == "首你好😀末尾"

    asyncio.run(run())
