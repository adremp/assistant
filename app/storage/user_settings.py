"""User settings storage using Redis."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class UserSettingsStorage:
    """Redis-based storage for user settings."""

    def __init__(self, redis: Redis):
        """
        Initialize user settings storage.

        Args:
            redis: Redis client instance
        """
        self.redis = redis
        self._prefix = "user_settings"

    def _make_key(self, user_id: int) -> str:
        """Generate Redis key for user settings."""
        return f"{self._prefix}:{user_id}"

    async def get_settings(self, user_id: int) -> dict[str, Any]:
        """
        Get all settings for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            User settings dictionary
        """
        key = self._make_key(user_id)
        data = await self.redis.get(key)
        if data is None:
            return {}
        return json.loads(data)

    async def set_setting(self, user_id: int, key: str, value: Any) -> None:
        """
        Set a single setting for a user.

        Args:
            user_id: Telegram user ID
            key: Setting key
            value: Setting value
        """
        settings = await self.get_settings(user_id)
        settings[key] = value
        redis_key = self._make_key(user_id)
        await self.redis.set(redis_key, json.dumps(settings))
        logger.debug(f"Set {key}={value} for user {user_id}")

    async def get_setting(self, user_id: int, key: str, default: Any = None) -> Any:
        """
        Get a single setting for a user.

        Args:
            user_id: Telegram user ID
            key: Setting key
            default: Default value if not set

        Returns:
            Setting value or default
        """
        settings = await self.get_settings(user_id)
        return settings.get(key, default)

    async def get_timezone(self, user_id: int, default: str | None = None) -> str | None:
        """
        Get user's timezone.

        Args:
            user_id: Telegram user ID
            default: Default timezone

        Returns:
            User's timezone string
        """
        return await self.get_setting(user_id, "timezone", default)

    async def set_timezone(self, user_id: int, timezone: str) -> None:
        """
        Set user's timezone.

        Args:
            user_id: Telegram user ID
            timezone: Timezone string (e.g., "Asia/Almaty")
        """
        await self.set_setting(user_id, "timezone", timezone)
        logger.info(f"Set timezone={timezone} for user {user_id}")
