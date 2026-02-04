"""MCP Google server configuration."""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://assistant-redis:6379/0"
    token_ttl_seconds: int = 2592000
    google_credentials_path: Path = Path("credentials.json")
    google_redirect_uri: str | None = None
    mcp_port: int = 8001


@lru_cache
def get_settings() -> Settings:
    return Settings()
