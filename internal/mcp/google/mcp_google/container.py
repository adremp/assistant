"""Lazy-init dependency container for MCP Google."""

from pkg.token_storage import TokenStorage
from redis.asyncio import Redis

from mcp_google.config import get_settings
from mcp_google.repository.auth_repo import AuthRepo
from mcp_google.services.calendar_service import CalendarService
from mcp_google.services.tasks_service import TasksService

settings = get_settings()

_redis: Redis | None = None
_token_storage: TokenStorage | None = None
_auth_repo: AuthRepo | None = None
_calendar_service: CalendarService | None = None
_tasks_service: TasksService | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url)
    return _redis


async def get_auth_repo() -> AuthRepo:
    global _token_storage, _auth_repo
    if _auth_repo is None:
        redis = await get_redis()
        _token_storage = TokenStorage(redis, settings.token_ttl_seconds)
        _auth_repo = AuthRepo(_token_storage, settings.google_credentials_path)
    return _auth_repo


async def get_calendar_service() -> CalendarService:
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = CalendarService()
    return _calendar_service


async def get_tasks_service() -> TasksService:
    global _tasks_service
    if _tasks_service is None:
        _tasks_service = TasksService()
    return _tasks_service
