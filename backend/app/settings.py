from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://coursework:coursework@localhost:5433/coursework"
    cors_origins: str = "http://localhost:8080,http://localhost:5173"
    file_root: Path = Path("./data/files")
    session_hours: int = 24
    secure_cookies: bool = False
    max_file_size_bytes: int = 100 * 1024 * 1024
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
