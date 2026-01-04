"""Completed reminder storage for tracking user responses."""

import json
import logging
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class CompletedReminderStorage:
    """Store completed reminder responses in Redis."""

    def __init__(self, redis: Redis, ttl: int = 2592000):
        """
        Initialize completed reminder storage.

        Args:
            redis: Redis client instance
            ttl: Time-to-live for completed reminders in seconds (default: 30 days)
        """
        self.redis = redis
        self.ttl = ttl
        self._prefix = "completed_reminder"
        self._user_list_prefix = "user_completed_reminders"

    def _make_key(self, completed_id: str) -> str:
        """Generate Redis key for a completed reminder."""
        return f"{self._prefix}:{completed_id}"

    def _make_user_list_key(self, user_id: int) -> str:
        """Generate Redis key for user's completed reminders list."""
        return f"{self._user_list_prefix}:{user_id}"

    async def save_completed(
        self,
        user_id: int,
        reminder_id: str,
        template: str,
        response: str,
        completed_at: datetime | None = None,
    ) -> str:
        """
        Save completed reminder with user's response.

        Args:
            user_id: Telegram user ID
            reminder_id: ID of the original reminder
            template: The template that was sent
            response: User's response (text or transcribed voice)
            completed_at: Completion timestamp (defaults to now)

        Returns:
            Generated completed reminder ID
        """
        import uuid

        completed_id = str(uuid.uuid4())
        if completed_at is None:
            completed_at = datetime.now()

        data = {
            "id": completed_id,
            "user_id": user_id,
            "reminder_id": reminder_id,
            "template": template,
            "response": response,
            "completed_at": completed_at.isoformat(),
        }

        # Save completed reminder
        key = self._make_key(completed_id)
        await self.redis.setex(key, self.ttl, json.dumps(data))

        # Add to user's list (using sorted set with timestamp as score)
        user_key = self._make_user_list_key(user_id)
        score = completed_at.timestamp()
        await self.redis.zadd(user_key, {completed_id: score})

        logger.info(f"Saved completed reminder {completed_id} for user {user_id}")
        return completed_id

    async def get_completed(
        self,
        user_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get completed reminders for user (most recent first).

        Args:
            user_id: Telegram user ID
            limit: Maximum number of entries to return

        Returns:
            List of completed reminder data dictionaries
        """
        user_key = self._make_user_list_key(user_id)
        
        # Get most recent completed reminder IDs
        completed_ids = await self.redis.zrevrange(user_key, 0, limit - 1)

        results = []
        for completed_id in completed_ids:
            completed_id_str = completed_id.decode() if isinstance(completed_id, bytes) else completed_id
            key = self._make_key(completed_id_str)
            data = await self.redis.get(key)
            if data:
                results.append(json.loads(data))

        return results
