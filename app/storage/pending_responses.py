"""Pending response storage for tracking reminder responses."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class PendingResponseStorage:
    """Track pending reminder responses in Redis."""

    def __init__(self, redis: Redis, ttl: int = 3600):
        """
        Initialize pending response storage.

        Args:
            redis: Redis client instance
            ttl: Time-to-live for pending state in seconds (default: 1 hour)
        """
        self.redis = redis
        self.ttl = ttl
        self._prefix = "pending_response"

    def _make_key(self, user_id: int) -> str:
        """Generate Redis key for user's pending response."""
        return f"{self._prefix}:{user_id}"

    async def set_pending(
        self,
        user_id: int,
        reminder_id: str,
        template: str,
    ) -> None:
        """
        Mark that we're waiting for a response from user.

        Args:
            user_id: Telegram user ID
            reminder_id: ID of the reminder that triggered this
            template: The template that was sent to the user
        """
        key = self._make_key(user_id)
        data = {
            "reminder_id": reminder_id,
            "template": template,
            "sent_at": __import__("datetime").datetime.now().isoformat(),
        }
        await self.redis.setex(key, self.ttl, json.dumps(data))
        logger.debug(f"Set pending response for user {user_id}, reminder {reminder_id}")

    async def get_pending(self, user_id: int) -> dict[str, Any] | None:
        """
        Get pending reminder info for user.

        Args:
            user_id: Telegram user ID

        Returns:
            Pending response data or None if not waiting
        """
        key = self._make_key(user_id)
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def clear_pending(self, user_id: int) -> bool:
        """
        Clear pending state for user.

        Args:
            user_id: Telegram user ID

        Returns:
            True if cleared, False if nothing was pending
        """
        key = self._make_key(user_id)
        result = await self.redis.delete(key)
        if result:
            logger.debug(f"Cleared pending response for user {user_id}")
        return bool(result)
