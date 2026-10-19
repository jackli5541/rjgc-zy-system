from app.core.ai_client import OpenAICompatibleClient
from app.core.errors import ApiError
from app.settings import settings


def require_grading_config():
    if not settings.ai_grading_enabled:
        raise ApiError(503, "AI_GRADING_DISABLED", "AI 批改尚未启用，请配置 AI_GRADING_ENABLED=true")
    if settings.ai_provider != "openai_compatible" or not settings.ai_base_url.strip() or not settings.ai_chat_model.strip():
        raise ApiError(503, "AI_GRADING_CONFIG_INVALID", "AI 批改模型接口配置不完整")


def get_ai_client(transport=None):
    client = OpenAICompatibleClient(
        enabled=settings.ai_grading_enabled, provider=settings.ai_provider,
        base_url=settings.ai_base_url, api_key=settings.ai_api_key,
        model=settings.ai_chat_model, timeout=settings.ai_request_timeout_seconds,
        max_output_tokens=settings.ai_grading_max_output_tokens, module="grading", label="AI 批改", transport=transport,
    )
    client.temperature = 0
    client.structured_output = True
    return client
