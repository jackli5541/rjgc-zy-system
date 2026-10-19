from app.core.ai_client import AiClientError, OpenAICompatibleClient as BaseClient, _unsupported_models
from app.settings import settings


class OpenAICompatibleClient(BaseClient):
    def __init__(self, transport=None):
        super().__init__(
            enabled=settings.ai_teacher_enabled, provider=settings.ai_provider,
            base_url=settings.ai_base_url, api_key=settings.ai_api_key, model=settings.ai_chat_model,
            timeout=settings.ai_request_timeout_seconds, max_output_tokens=settings.ai_teacher_max_output_tokens,
            module="teacher", label="AI 老师", transport=transport,
        )


def get_ai_client():
    return OpenAICompatibleClient()
