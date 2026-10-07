from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

from app.settings import settings


logger = logging.getLogger(__name__)
_unsupported_models: dict[tuple[str, str], float] = {}


class AiClientError(RuntimeError):
    def __init__(self, message: str, code: str = "upstream_error") -> None:
        super().__init__(message)
        self.code = code


class OpenAICompatibleClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = settings.ai_base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.hostname == "api.deepseek.com" and parsed.path in {"", "/"}:
            self.base_url += "/v1"
        self.api_key = settings.ai_api_key
        self.timeout = settings.ai_request_timeout_seconds
        self.transport = transport
        self.fallback_model = "deepseek-chat" if parsed.hostname == "api.deepseek.com" and settings.ai_chat_model == "deepseek-flash" else None

    async def _stream_model(self, client: httpx.AsyncClient, model: str, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "stream": True,
            "max_tokens": settings.ai_teacher_max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        started = time.perf_counter()
        first_content_ms = None
        content_chunks = 0
        leading_whitespace = ""
        reasoning_chunks = 0
        finish_reason = None
        status = None
        try:
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=headers) as response:
                status = response.status_code
                if response.is_error:
                    body = (await response.aread())[:2048]
                    try:
                        detail = str(json.loads(body).get("error", {}).get("message", ""))
                    except (ValueError, AttributeError, TypeError):
                        detail = ""
                    unsupported = status in {400, 404} and ("model" in detail.lower() or "模型" in detail or "not found" in detail.lower())
                    code = "unsupported_model" if unsupported else "http_error"
                    raise AiClientError("模型不可用，请稍后重试" if unsupported else "模型服务调用失败，请稍后重试", code)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                        choice = data["choices"][0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        reasoning = delta.get("reasoning_content")
                        finish_reason = choice.get("finish_reason") or finish_reason
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                        raise AiClientError("模型服务返回格式不正确", "invalid_response") from exc
                    if reasoning:
                        reasoning_chunks += 1
                    if content:
                        if not content_chunks and not str(content).strip():
                            leading_whitespace += str(content)
                            continue
                        content_chunks += 1
                        if first_content_ms is None:
                            first_content_ms = round((time.perf_counter() - started) * 1000)
                        yield leading_whitespace + str(content)
                        leading_whitespace = ""
                if finish_reason == "length":
                    raise AiClientError("模型输出长度不足，请重试", "token_limit")
                if not content_chunks:
                    if reasoning_chunks:
                        raise AiClientError("模型只返回了推理内容，请重试", "reasoning_only")
                    raise AiClientError("模型服务没有返回正文，请重试", "empty_content")
        except httpx.HTTPError as exc:
            raise AiClientError("模型服务连接失败，请稍后重试", "connection_error") from exc
        finally:
            logger.info(
                "ai_teacher_model model=%s status=%s finish_reason=%s content_chunks=%s reasoning_chunks=%s first_content_ms=%s duration_ms=%s",
                model, status, finish_reason, content_chunks, reasoning_chunks, first_content_ms,
                round((time.perf_counter() - started) * 1000),
            )

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if not settings.ai_teacher_enabled:
            raise AiClientError("AI 老师尚未启用，请先配置 AI_TEACHER_ENABLED=true 和模型服务地址")
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            models = [settings.ai_chat_model]
            if self.fallback_model:
                models.append(self.fallback_model)
                cache_key = (self.base_url, settings.ai_chat_model)
                if _unsupported_models.get(cache_key, 0) > time.monotonic():
                    models.pop(0)
            for index, model in enumerate(models):
                emitted = False
                try:
                    async for delta in self._stream_model(client, model, messages):
                        emitted = True
                        yield delta
                    return
                except AiClientError as exc:
                    if exc.code == "unsupported_model" and model == settings.ai_chat_model and self.fallback_model:
                        _unsupported_models[(self.base_url, model)] = time.monotonic() + 600
                    retry = index == 0 and model == settings.ai_chat_model and not emitted and self.fallback_model and exc.code in {
                        "unsupported_model", "empty_content", "reasoning_only", "token_limit",
                    }
                    if not retry:
                        raise
                    logger.warning("ai_teacher_fallback primary=%s fallback=%s reason=%s", model, self.fallback_model, exc.code)


def get_ai_client() -> OpenAICompatibleClient:
    if settings.ai_provider != "openai_compatible":
        raise AiClientError("当前仅支持 OpenAI-compatible 模型接口")
    return OpenAICompatibleClient()
