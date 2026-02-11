"""MCP Summaries server configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://assistant-redis:6379/0"
    token_ttl_seconds: int = 2592000
    telethon_api_id: int
    telethon_api_hash: str
    llm_api_key: str
    llm_base_url: str = "https://api.x.ai/v1"
    llm_model: str = "grok-3"
    llm_temperature: float = 0.7
    llm_timeout: float = 30.0
    llm_tpm_limit: int = 100000
    mcp_port: int = 8002


@lru_cache
def get_settings() -> Settings:
    return Settings()
