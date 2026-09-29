from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str = "mssql+pyodbc://sa:Coursework_2026!@localhost:1433/coursework?driver=ODBC+Driver+17+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes"
    cors_origins: str = "http://localhost:8080,http://localhost:5173"
    oss_endpoint: str = "https://oss-cn-hangzhou.aliyuncs.com"
    oss_bucket: str = "se-lab"
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_key_prefix: str = ""
    oss_preview_url_ttl_seconds: int = 300
    session_hours: int = 24
    secure_cookies: bool = False
    trusted_proxy_cidrs: str = "127.0.0.1/32,::1/128"
    max_file_size_bytes: int = 500 * 1024 * 1024
    markdown_max_bytes: int = 5 * 1024 * 1024
    markdown_image_max_bytes: int = 10 * 1024 * 1024
    markdown_image_max_pixels: int = 40_000_000
    markdown_asset_orphan_hours: int = 24
    export_archive_hours: int = 24
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    ai_teacher_enabled: bool = False
    ai_provider: str = "openai_compatible"
    ai_base_url: str = "http://localhost:11434/v1"
    ai_api_key: str = "local-dev"
    ai_chat_model: str = "qwen2.5:7b-instruct"
    ai_embedding_model: str = "bge-m3"
    ai_rerank_model: str = ""
    ai_request_timeout_seconds: int = 60
    ai_teacher_max_history: int = 12
    ai_teacher_max_context_chars: int = 12000
    # 900 tokens frequently truncates Markdown explanations before the model
    # reaches a natural conclusion. Keep a bounded default for low-bandwidth
    # deployments; operators can tune this with AI_TEACHER_MAX_OUTPUT_TOKENS.
    ai_teacher_max_output_tokens: int = 1600
    ai_teacher_max_concurrent_per_worker: int = 4
    ai_teacher_max_quote_chars: int = 1200
    # Load the repository-level environment regardless of whether the API is
    # started from the repository root or from backend/.
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        extra="ignore",
    )

settings = Settings()
