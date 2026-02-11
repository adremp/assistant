"""Lazy-init dependency container for MCP Summaries."""

from pkg.token_storage import TokenStorage
from pkg.watcher_storage import WatcherStorage
from redis.asyncio import Redis

from mcp_summaries.config import get_settings
from mcp_summaries.repository.telethon_repo import TelethonRepo
from mcp_summaries.services.auth_service import AuthService
from mcp_summaries.services.summary_service import SummaryService

settings = get_settings()

_redis: Redis | None = None
_token_storage: TokenStorage | None = None
_watcher_storage: WatcherStorage | None = None
_auth_service: AuthService | None = None
_summary_service: SummaryService | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url)
    return _redis


async def get_token_storage() -> TokenStorage:
    global _token_storage
    if _token_storage is None:
        redis = await get_redis()
        _token_storage = TokenStorage(redis, settings.token_ttl_seconds)
    return _token_storage


async def get_watcher_storage() -> WatcherStorage:
    global _watcher_storage
    if _watcher_storage is None:
        redis = await get_redis()
        _watcher_storage = WatcherStorage(redis)
    return _watcher_storage


async def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        redis = await get_redis()
        ts = await get_token_storage()
        _auth_service = AuthService(settings, redis, ts)
    return _auth_service


async def get_summary_service() -> SummaryService:
    global _summary_service
    if _summary_service is None:
        _summary_service = SummaryService(settings)
    return _summary_service


def create_telethon_repo(session_string: str | None = None) -> TelethonRepo:
    return TelethonRepo(settings, session_string)


async def create_user_telethon_repo(user_id: int) -> TelethonRepo | None:
    """Create a TelethonRepo with the user's saved session, or None if not authenticated."""
    ts = await get_token_storage()
    session = await ts.get_telethon_session(user_id)
    if not session:
        return None
    return create_telethon_repo(session)
