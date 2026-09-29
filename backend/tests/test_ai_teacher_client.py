import asyncio
import json

import httpx
import pytest

from app.modules.ai_teacher.client import AiClientError, OpenAICompatibleClient, _unsupported_models
from app.settings import settings


@pytest.fixture(autouse=True)
def clear_model_cache():
    _unsupported_models.clear()
    yield
    _unsupported_models.clear()


def sse(*choices):
    return "".join(f"data: {json.dumps({'choices': [choice]})}\n\n" for choice in choices) + "data: [DONE]\n\n"


def run_client(monkeypatch, handler):
    monkeypatch.setattr(settings, "ai_teacher_enabled", True)
    monkeypatch.setattr(settings, "ai_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "ai_chat_model", "deepseek-flash")
    models = []

    def respond(request):
        model = json.loads(request.content)["model"]
        models.append(model)
        return handler(model)

    client = OpenAICompatibleClient(transport=httpx.MockTransport(respond))

    async def collect():
        return [chunk async for chunk in client.stream_chat([{"role": "user", "content": "课程问题"}])]

    return collect, models


def test_flash_content_streams_without_fallback(monkeypatch):
    collect, models = run_client(monkeypatch, lambda _: httpx.Response(200, text=sse(
        {"delta": {"content": "需求"}, "finish_reason": None},
        {"delta": {"content": "分析"}, "finish_reason": "stop"},
    )))
    assert asyncio.run(collect()) == ["需求", "分析"]
    assert models == ["deepseek-flash"]


@pytest.mark.parametrize("flash_response", [
    httpx.Response(400, json={"error": {"message": "Model deepseek-flash does not exist"}}),
    httpx.Response(200, text=sse({"delta": {"reasoning_content": "思考"}, "finish_reason": "stop"})),
    httpx.Response(200, text=sse({"delta": {}, "finish_reason": "stop"})),
    httpx.Response(200, text=sse({"delta": {"content": "  \n"}, "finish_reason": "stop"})),
    httpx.Response(200, text=sse({"delta": {"reasoning_content": "思考"}, "finish_reason": "length"})),
])
def test_flash_unavailable_retries_chat_once(monkeypatch, flash_response):
    collect, models = run_client(monkeypatch, lambda model: flash_response if model == "deepseek-flash" else httpx.Response(
        200, text=sse({"delta": {"content": "可以先确定参与者。"}, "finish_reason": "stop"}),
    ))
    assert asyncio.run(collect()) == ["可以先确定参与者。"]
    assert models == ["deepseek-flash", "deepseek-chat"]


def test_partial_flash_answer_never_mix_with_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ai_teacher_enabled", True)
    monkeypatch.setattr(settings, "ai_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "ai_chat_model", "deepseek-flash")
    models = []

    def respond(request):
        models.append(json.loads(request.content)["model"])
        return httpx.Response(200, text=sse(
            {"delta": {"content": "部分"}, "finish_reason": None},
            {"delta": {}, "finish_reason": "length"},
        ))

    async def run():
        chunks = []
        with pytest.raises(AiClientError) as error:
            client = OpenAICompatibleClient(transport=httpx.MockTransport(respond))
            async for chunk in client.stream_chat([{"role": "user", "content": "课程问题"}]):
                chunks.append(chunk)
        return chunks, error.value.code

    chunks, code = asyncio.run(run())
    assert chunks == ["部分"]
    assert code == "token_limit"
    assert models == ["deepseek-flash"]


def test_two_empty_models_return_retryable_error(monkeypatch):
    collect, models = run_client(monkeypatch, lambda _: httpx.Response(200, text=sse({"delta": {}, "finish_reason": "stop"})))
    with pytest.raises(AiClientError) as error:
        asyncio.run(collect())
    assert error.value.code == "empty_content"
    assert models == ["deepseek-flash", "deepseek-chat"]


def test_unsupported_flash_is_skipped_briefly_on_next_request(monkeypatch):
    collect, models = run_client(monkeypatch, lambda model: httpx.Response(
        400, json={"error": {"message": "Model deepseek-flash not found"}},
    ) if model == "deepseek-flash" else httpx.Response(
        200, text=sse({"delta": {"content": "概念说明"}, "finish_reason": "stop"}),
    ))
    assert asyncio.run(collect()) == ["概念说明"]
    assert asyncio.run(collect()) == ["概念说明"]
    assert models == ["deepseek-flash", "deepseek-chat", "deepseek-chat"]


def test_cached_fallback_failure_is_not_reported_as_success(monkeypatch):
    collect, models = run_client(monkeypatch, lambda model: httpx.Response(
        400, json={"error": {"message": "Model deepseek-flash not found"}},
    ) if model == "deepseek-flash" else httpx.Response(200, text=sse({"delta": {}, "finish_reason": "stop"})))
    with pytest.raises(AiClientError):
        asyncio.run(collect())
    with pytest.raises(AiClientError) as error:
        asyncio.run(collect())
    assert error.value.code == "empty_content"
    assert models == ["deepseek-flash", "deepseek-chat", "deepseek-chat"]


def test_rate_limit_is_not_retried_with_same_provider(monkeypatch):
    collect, models = run_client(monkeypatch, lambda _: httpx.Response(429, json={"error": {"message": "Rate limited"}}))
    with pytest.raises(AiClientError) as error:
        asyncio.run(collect())
    assert error.value.code == "http_error"
    assert models == ["deepseek-flash"]
