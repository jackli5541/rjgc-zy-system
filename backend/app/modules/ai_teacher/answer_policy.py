from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import suppress


SELF_CHECK_GUIDANCE = "我不能检查或评价你已有的答案。你可以对照作业要求逐项自查：确认每个任务都有对应内容，术语和图表前后一致，并用课程概念核对关键步骤。若某个概念不清楚，可以单独提问。"
_WORK = r"答案|草稿|作业|文档|写的|写好|已写|已有的|内容"
_REVIEW = r"检查|批改|审阅|评估|评价|核对|看看|看一看|改改|挑错|找错|指出.*(?:错误|问题|遗漏)"
_REQUEST = re.compile(rf"(?:帮我|替我|给我|你来|请你|能否|可否|想让你|让我|麻烦你).{{0,20}}(?:{_REVIEW}).{{0,25}}(?:{_WORK})|(?:帮我|替我|给我|你来|请你|能否|可否|想让你|让我|麻烦你).{{0,20}}(?:{_WORK}).{{0,25}}(?:{_REVIEW})|(?:{_REVIEW}).{{0,12}}(?:我的|这份|已有的)?(?:答案|草稿)|(?:我的|这份|已有的)?(?:答案|草稿).{{0,12}}(?:对吗|正确吗|有错吗|有没有问题|怎么样)")
_OFFER = re.compile(rf"(?:想让|要不要|需要|可以|是否|愿意|发给我|我来|我帮|帮你|让我).{{0,30}}(?:{_REVIEW}).{{0,30}}(?:{_WORK})|(?:想让|要不要|需要|可以|是否|愿意|发给我|我来|我帮|帮你|让我).{{0,30}}(?:{_WORK}).{{0,30}}(?:{_REVIEW})|(?:{_WORK}).{{0,30}}(?:我帮你|我来).{{0,12}}(?:看看|检查|批改)")
_JUDGMENT = re.compile(r"(?:你的|你写的|草稿|答案|作业).{0,35}(?:写错|做错|不对|正确|错误|遗漏|漏了|完成了|已经做完|已经写了)|(?:写错|做错|不对|正确|错误|遗漏|漏了).{0,35}(?:你的|你写的|草稿|答案|作业)")
_SENSITIVE_START = re.compile(r"想让|要不要|需要|可以|是否|愿意|发给我|我来|我帮|帮你|让我|你的|你写的|草稿|答案|作业|写错|做错|不对|正确|错误|遗漏|漏了")


def asks_for_answer_review(question: str) -> bool:
    return bool(_REQUEST.search(question))


def safe_answer_segment(segment: str) -> str:
    if _OFFER.search(segment) or _JUDGMENT.search(segment):
        return SELF_CHECK_GUIDANCE
    return segment


async def guarded_answer(deltas: AsyncIterator[str]) -> AsyncIterator[str]:
    pending = ""
    try:
        async for delta in deltas:
            pending += delta
            while True:
                boundaries = [pending.find(char) for char in "。！？\n" if char in pending]
                if not boundaries:
                    break
                end = min(boundaries) + 1
                yield safe_answer_segment(pending[:end])
                pending = pending[end:]
            if len(pending) >= 28 and not _OFFER.search(pending) and not _JUDGMENT.search(pending):
                release_end = len(pending) - (80 if len(pending) > 240 else 16)
                sensitive = _SENSITIVE_START.search(pending)
                if sensitive and len(pending) <= 240:
                    release_end = min(release_end, sensitive.start())
                if release_end > 0:
                    yield pending[:release_end]
                    pending = pending[release_end:]
        if pending:
            yield safe_answer_segment(pending)
    finally:
        close = getattr(deltas, "aclose", None)
        if close:
            with suppress(GeneratorExit):
                await close()
