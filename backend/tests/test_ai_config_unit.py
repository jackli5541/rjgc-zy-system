"""Shared AI configuration tests. No database or live model calls."""
import asyncio
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.errors import ApiError
from app.settings import Settings
from app.modules.ai_teacher import client as teacher
from app.modules.ai_grading import client as grading
from app.core.ai_client import AiClientError
from app import worker


def config(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_both_clients_use_shared_endpoint_credentials_model_and_timeout(monkeypatch):
    s = config(ai_teacher_enabled=True, ai_grading_enabled=True, ai_base_url='https://shared.test/v1',
               ai_api_key='shared', ai_chat_model='shared-model', ai_request_timeout_seconds=42)
    monkeypatch.setattr(teacher, 'settings', s)
    monkeypatch.setattr(grading, 'settings', s)
    grading.require_grading_config()
    for c in (teacher.get_ai_client(), grading.get_ai_client()):
        assert (c.enabled, c.base_url, c.api_key, c.model, c.timeout) == (
            True, 'https://shared.test/v1', 'shared', 'shared-model', 42,
        )


def test_obsolete_module_environment_variables_are_ignored(monkeypatch, tmp_path):
    lines = []
    for module in ('TEACHER', 'GRADING'):
        for name, value in {'PROVIDER': 'obsolete', 'BASE_URL': 'https://obsolete.test/v1',
                            'API_KEY': 'obsolete', 'CHAT_MODEL': 'obsolete',
                            'REQUEST_TIMEOUT_SECONDS': '999'}.items():
            key = f'AI_{module}_{name}'
            monkeypatch.setenv(key, value)
            lines.append(f'{key}={value}')
    env_file = tmp_path / '.env'
    env_file.write_text('\n'.join(lines), encoding='utf-8')
    s = Settings(_env_file=env_file, ai_provider='openai_compatible', ai_base_url='https://shared.test/v1',
                 ai_api_key='shared', ai_chat_model='shared-model', ai_request_timeout_seconds=42)
    monkeypatch.setattr(teacher, 'settings', s)
    monkeypatch.setattr(grading, 'settings', s)
    for c in (teacher.get_ai_client(), grading.get_ai_client()):
        assert (c.base_url, c.api_key, c.model, c.timeout) == ('https://shared.test/v1', 'shared', 'shared-model', 42)


@pytest.mark.parametrize('teacher_enabled,grading_enabled', [(False, True), (True, False)])
def test_module_switches_remain_independent(monkeypatch, teacher_enabled, grading_enabled):
    s = config(ai_teacher_enabled=teacher_enabled, ai_grading_enabled=grading_enabled)
    monkeypatch.setattr(grading, 'settings', s)
    monkeypatch.setattr(teacher, 'settings', s)
    assert teacher.get_ai_client().enabled == teacher_enabled
    assert grading.get_ai_client().enabled == grading_enabled
    disabled = teacher.get_ai_client() if not teacher_enabled else grading.get_ai_client()
    with pytest.raises(AiClientError, match='AI_TEACHER_ENABLED' if not teacher_enabled else 'AI_GRADING_ENABLED'):
        asyncio.run(anext(disabled.stream_chat([])))


@pytest.mark.parametrize('invalid', [
    {'ai_provider': 'unsupported'}, {'ai_base_url': '  '}, {'ai_chat_model': ''},
])
def test_grading_validates_shared_configuration(monkeypatch, invalid):
    monkeypatch.setattr(grading, 'settings', config(ai_grading_enabled=True, **invalid))
    with pytest.raises(ApiError) as error:
        grading.require_grading_config()
    assert error.value.status == 503
    assert error.value.code == 'AI_GRADING_CONFIG_INVALID'


def test_shared_service_keeps_module_specific_generation_parameters(monkeypatch):
    s = config(ai_teacher_enabled=True, ai_grading_enabled=True, ai_base_url='https://api.deepseek.com/v1',
               ai_api_key='test-key', ai_chat_model='deepseek-chat',
               ai_teacher_max_output_tokens=1600, ai_grading_max_output_tokens=8192)
    monkeypatch.setattr(teacher, 'settings', s)
    monkeypatch.setattr(grading, 'settings', s)
    requests = []

    def respond(request):
        requests.append((str(request.url), request.headers['authorization'], json.loads(request.content)))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')

    transport = httpx.MockTransport(respond)

    async def run():
        for c in (teacher.OpenAICompatibleClient(transport), grading.get_ai_client(transport)):
            assert ''.join([part async for part in c.stream_chat([{'role': 'user', 'content': 'hello'}])]) == 'ok'

    asyncio.run(run())
    for url, authorization, payload in requests:
        assert url == 'https://api.deepseek.com/v1/chat/completions'
        assert authorization == 'Bearer test-key'
        assert payload['model'] == 'deepseek-chat'
        assert payload['stream'] is True
    teacher_payload, grading_payload = [request[2] for request in requests]
    assert teacher_payload['max_tokens'] == 1600 and teacher_payload['temperature'] == 0.3
    assert 'response_format' not in teacher_payload and 'thinking' not in teacher_payload
    assert grading_payload['max_tokens'] == 8192 and grading_payload['temperature'] == 0
    assert grading_payload['response_format'] == {'type': 'json_object'}
    assert grading_payload['thinking'] == {'type': 'disabled'}


def test_disabled_grading_blocks_enqueue_and_worker_claim(monkeypatch):
    s = config(ai_grading_enabled=False)
    monkeypatch.setattr(grading, 'settings', s)
    with pytest.raises(Exception, match='AI 批改尚未启用'):
        grading.require_grading_config()
    monkeypatch.setattr(worker, 'settings', s)
    db = MagicMock()
    db.scalar.return_value = None
    with patch.object(worker.SessionLocal, 'begin') as begin:
        begin.return_value.__enter__.return_value = db
        worker.run_once(run_maintenance=False)
    query = db.scalar.call_args.args[0]
    assert 'NOT IN' in str(query)
    assert 'AI_GRADING' in str(query.compile(compile_kwargs={'literal_binds': True}))


def test_disabled_grading_keeps_non_ai_jobs_running(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4
    monkeypatch.setattr(worker, 'settings', config(ai_grading_enabled=False))
    job = SimpleNamespace(id=uuid4(), kind='OSS_DELETE', payload={'keys': ['example']}, attempts=0)
    db = MagicMock()
    db.scalar.return_value = job
    with patch.object(worker.SessionLocal, 'begin') as begin, patch.object(worker, 'process_claimed_job') as process:
        begin.return_value.__enter__.return_value = db
        worker.run_once(run_maintenance=False)
        process.assert_called_once_with(job.id, 'OSS_DELETE', job.payload, None, ['example'])
    assert job.status == 'RUNNING'
