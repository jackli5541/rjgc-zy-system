from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str = "mssql+pyodbc://sa:Coursework_2026!@localhost:1433/coursework?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes"
    cors_origins: str = "http://localhost:8080,http://localhost:5173"
    file_root: Path = Path("./data/files")
    session_hours: int = 24
    secure_cookies: bool = False
    trusted_proxy_cidrs: str = "127.0.0.1/32,::1/128"
    max_file_size_bytes: int = 100 * 1024 * 1024
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
