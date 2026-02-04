"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram Bot
    telegram_bot_token: str
    telegram_webhook_url: str | None = None
    telegram_webhook_secret: str | None = None

    # Google OAuth2
    google_credentials_path: Path = Path("credentials.json")
    google_redirect_uri: str | None = None

    # LLM Provider (OpenAI-compatible: Grok, OpenAI, etc.)
    llm_api_key: str
    llm_base_url: str = "https://api.x.ai/v1"
    llm_model: str = "grok-3"
    llm_temperature: float = 0.7
    llm_max_retries: int = 3
    llm_timeout: float = 30.0
    llm_tpm_limit: int = 100000

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    conversation_ttl_seconds: int = 86400  # 24 hours
    token_ttl_seconds: int = 2592000  # 30 days

    # MCP Server URLs (internal container port is 8000, HTTP transport)
    mcp_google_url: str = "http://mcp-google:8000/mcp"
    mcp_summaries_url: str = "http://mcp-summaries:8000/mcp"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
