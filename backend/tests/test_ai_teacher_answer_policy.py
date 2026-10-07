import asyncio

from app.modules.ai_teacher.answer_policy import SELF_CHECK_GUIDANCE, asks_for_answer_review, guarded_answer


def test_review_request_and_regular_course_question():
    assert asks_for_answer_review("帮我检查已有的答案")
    assert asks_for_answer_review("检查一下我的答案")
    assert asks_for_answer_review("我的答案对吗")
    assert not asks_for_answer_review("怎样检查需求文档的一致性？")
    assert not asks_for_answer_review("什么是 ER 图？")


def test_guard_never_emits_or_retains_review_offer():
    async def source():
        for part in ("首先明确实体关系。\n", "想让我检", "查已有的答", "案？"):
            yield part

    async def run():
        return [item async for item in guarded_answer(source())]

    result = asyncio.run(run())
    assert result == ["首先明确实体关系。", "\n", SELF_CHECK_GUIDANCE]
    assert "想让我检查" not in "".join(result)


def test_guard_replaces_answer_judgment_and_preserves_normal_guidance():
    async def source():
        yield "你写的答案已经做完了。可以先列出实体，再标注关系。"

    async def run():
        return [item async for item in guarded_answer(source())]

    assert asyncio.run(run()) == [SELF_CHECK_GUIDANCE, "可以先列出实体，再标注关系。"]


def test_guard_closes_upstream_when_chat_stops():
    async def run():
        closed = asyncio.Event()

        async def source():
            try:
                yield "先理解参与者。"
                await asyncio.Event().wait()
            finally:
                closed.set()

        stream = guarded_answer(source())
        assert await anext(stream) == "先理解参与者。"
        await stream.aclose()
        assert closed.is_set()

    asyncio.run(run())


def test_guard_releases_safe_prefix_before_long_sentence_ends():
    async def run():
        resume = asyncio.Event()

        async def source():
            yield "先列出系统边界，再把参与者与外部系统分开，记录他们和系统之间的交互"
            await resume.wait()
            yield "，最后逐条写成用例。"

        stream = guarded_answer(source())
        first = await asyncio.wait_for(anext(stream), 0.5)
        assert first.startswith("先列出系统边界")
        resume.set()
        assert "".join([first, *[item async for item in stream]]).endswith("最后逐条写成用例。")

    asyncio.run(run())
