"""OAuth2 token storage using Redis."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class TokenStorage:
    """Redis-based storage for OAuth2 tokens."""

    def __init__(self, redis: Redis, ttl: int = 2592000):
        """
        Initialize token storage.

        Args:
            redis: Redis client instance
            ttl: Token time-to-live in seconds (default: 30 days)
        """
        self.redis = redis
        self.ttl = ttl
        self._prefix = "oauth_token"

    def _make_key(self, user_id: int) -> str:
        """Generate Redis key for user's token."""
        return f"{self._prefix}:{user_id}"

    async def save_token(self, user_id: int, token_data: dict[str, Any]) -> None:
        """
        Save OAuth2 token data for a user.

        Args:
            user_id: Telegram user ID
            token_data: Token data dictionary (access_token, refresh_token, etc.)
        """
        key = self._make_key(user_id)
        await self.redis.setex(
            key,
            self.ttl,
            json.dumps(token_data),
        )
        logger.debug(f"Saved token for user {user_id}")

    async def load_token(self, user_id: int) -> dict[str, Any] | None:
        """
        Load OAuth2 token data for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            Token data dictionary or None if not found
        """
        key = self._make_key(user_id)
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def delete_token(self, user_id: int) -> bool:
        """
        Delete OAuth2 token for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            True if token was deleted, False if not found
        """
        key = self._make_key(user_id)
        result = await self.redis.delete(key)
        if result:
            logger.debug(f"Deleted token for user {user_id}")
        return bool(result)

    async def has_token(self, user_id: int) -> bool:
        """
        Check if user has a stored token.

        Args:
            user_id: Telegram user ID

        Returns:
            True if token exists
        """
        key = self._make_key(user_id)
        return await self.redis.exists(key) > 0

    async def refresh_ttl(self, user_id: int) -> bool:
        """
        Refresh TTL for user's token.

        Args:
            user_id: Telegram user ID

        Returns:
            True if TTL was refreshed, False if token not found
        """
        key = self._make_key(user_id)
        return await self.redis.expire(key, self.ttl)

    async def get_user_timezone(self, user_id: int, default: str | None = None) -> str | None:
        """
        Get user's timezone from stored token data.

        Args:
            user_id: Telegram user ID
            default: Default timezone if not set

        Returns:
            User's timezone string
        """
        token_data = await self.load_token(user_id)
        if token_data is None:
            return default
        return token_data.get("timezone", default)

    async def set_user_timezone(self, user_id: int, timezone: str) -> None:
        """
        Set user's timezone in token data.

        Args:
            user_id: Telegram user ID
            timezone: Timezone string (e.g., "Asia/Almaty")
        """
        token_data = await self.load_token(user_id)
        if token_data is None:
            return
        token_data["timezone"] = timezone
        await self.save_token(user_id, token_data)
        logger.info(f"Saved timezone {timezone} for user {user_id}")
