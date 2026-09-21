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
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
