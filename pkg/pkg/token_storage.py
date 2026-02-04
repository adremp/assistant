"""OAuth2 token storage using Redis."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class TokenStorage:
    """Redis-based storage for OAuth2 tokens."""

    def __init__(self, redis: Redis, ttl: int = 2592000):
        self.redis = redis
        self.ttl = ttl
        self._prefix = "oauth_token"

    def _make_key(self, user_id: int) -> str:
        return f"{self._prefix}:{user_id}"

    async def save_token(self, user_id: int, token_data: dict[str, Any]) -> None:
        key = self._make_key(user_id)
        await self.redis.setex(key, self.ttl, json.dumps(token_data))
        logger.debug(f"Saved token for user {user_id}")

    async def load_token(self, user_id: int) -> dict[str, Any] | None:
        key = self._make_key(user_id)
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def delete_token(self, user_id: int) -> bool:
        key = self._make_key(user_id)
        result = await self.redis.delete(key)
        if result:
            logger.debug(f"Deleted token for user {user_id}")
        return bool(result)

    async def has_token(self, user_id: int) -> bool:
        key = self._make_key(user_id)
        return await self.redis.exists(key) > 0

    async def refresh_ttl(self, user_id: int) -> bool:
        key = self._make_key(user_id)
        return await self.redis.expire(key, self.ttl)

    async def get_user_timezone(self, user_id: int, default: str | None = None) -> str | None:
        token_data = await self.load_token(user_id)
        if token_data is None:
            return default
        return token_data.get("timezone", default)

    async def set_user_timezone(self, user_id: int, timezone: str) -> None:
        token_data = await self.load_token(user_id)
        if token_data is None:
            return
        token_data["timezone"] = timezone
        await self.save_token(user_id, token_data)
        logger.info(f"Saved timezone {timezone} for user {user_id}")

    async def get_telethon_session(self, user_id: int) -> str | None:
        token_data = await self.load_token(user_id)
        if token_data is None:
            return None
        return token_data.get("telethon_session")

    async def set_telethon_session(self, user_id: int, session_string: str) -> None:
        token_data = await self.load_token(user_id)
        if token_data is None:
            token_data = {}
        token_data["telethon_session"] = session_string
        await self.save_token(user_id, token_data)
        logger.info(f"Saved Telethon session for user {user_id}")

    async def clear_telethon_session(self, user_id: int) -> None:
        token_data = await self.load_token(user_id)
        if token_data and "telethon_session" in token_data:
            del token_data["telethon_session"]
            await self.save_token(user_id, token_data)
            logger.info(f"Cleared Telethon session for user {user_id}")
