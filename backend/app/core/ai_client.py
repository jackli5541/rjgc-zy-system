from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from urllib.parse import urlparse

import httpx



logger = logging.getLogger(__name__)
_unsupported_models: dict[tuple[str, str, str], float] = {}


class AiClientError(RuntimeError):
    def __init__(self, message: str, code: str = "upstream_error") -> None:
        super().__init__(message)
        self.code = code


class OpenAICompatibleClient:
    def __init__(self, *, enabled, provider, base_url, api_key, model, timeout, max_output_tokens, module, label, transport=None) -> None:
        self.enabled = enabled
        self.model = model
        self.module = module
        self.label = label
        if provider != "openai_compatible":
            raise AiClientError("当前仅支持 OpenAI-compatible 模型接口")
        self.base_url = base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.hostname == "api.deepseek.com" and parsed.path in {"", "/"}:
            self.base_url += "/v1"
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport
        self.max_output_tokens = max_output_tokens
        self.structured_output = False
        self.temperature = 0.3
        self.fallback_model = "deepseek-chat" if parsed.hostname == "api.deepseek.com" and self.model == "deepseek-flash" else None

    async def _stream_model(self, client: httpx.AsyncClient, model: str, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True,
            "max_tokens": self.max_output_tokens,
        }
        if self.structured_output:
            payload['response_format'] = {'type': 'json_object'}
            if urlparse(self.base_url).hostname == 'api.deepseek.com':
                payload['thinking'] = {'type': 'disabled'}
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
                "%s_model model=%s status=%s finish_reason=%s content_chunks=%s reasoning_chunks=%s first_content_ms=%s duration_ms=%s",
                self.module, model, status, finish_reason, content_chunks, reasoning_chunks, first_content_ms,
                round((time.perf_counter() - started) * 1000),
            )

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if not self.enabled:
            raise AiClientError(f"{self.label}尚未启用，请先配置 AI_{self.module.upper()}_ENABLED=true 和模型服务地址", "disabled")
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            models = [self.model]
            if self.fallback_model:
                models.append(self.fallback_model)
                cache_key = (self.module, self.base_url, self.model)
                if _unsupported_models.get(cache_key, 0) > time.monotonic():
                    models.pop(0)
            for index, model in enumerate(models):
                emitted = False
                try:
                    async with aclosing(self._stream_model(client, model, messages)) as source:
                        while True:
                            try:
                                # SSE heartbeats must not extend the wait for answer content.
                                delta = await asyncio.wait_for(anext(source), timeout=self.timeout)
                            except StopAsyncIteration:
                                break
                            except TimeoutError as exc:
                                message = "模型服务长时间未返回正文，请稍后重试" if not emitted else "模型服务回答中断，请稍后重试"
                                raise AiClientError(message, "content_timeout") from exc
                            emitted = True
                            yield delta
                    return
                except AiClientError as exc:
                    if exc.code == "unsupported_model" and model == self.model and self.fallback_model:
                        _unsupported_models[(self.module, self.base_url, model)] = time.monotonic() + 600
                    retry = index == 0 and model == self.model and not emitted and self.fallback_model and exc.code in {
                        "unsupported_model", "empty_content", "reasoning_only", "token_limit",
                    }
                    if not retry:
                        raise
                    logger.warning("%s_fallback primary=%s fallback=%s reason=%s", self.module, model, self.fallback_model, exc.code)
