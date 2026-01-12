"""Pending reminder confirmation storage."""

import json
import logging
import uuid
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class PendingReminderConfirmation:
    """Store pending reminder data awaiting user confirmation."""

    def __init__(self, redis: Redis, ttl: int = 300):
        """
        Initialize pending confirmation storage.

        Args:
            redis: Redis client instance
            ttl: Time-to-live in seconds (default: 5 minutes)
        """
        self.redis = redis
        self.ttl = ttl
        self._prefix = "pending_reminder_confirm"

    def _make_key(self, confirmation_id: str) -> str:
        """Generate Redis key for confirmation."""
        return f"{self._prefix}:{confirmation_id}"

    async def save_pending(
        self,
        user_id: int,
        template: str,
        schedule_type: str,
        time: str,
        timezone: str,
        weekday: int | None = None,
        summary: str | None = None,
    ) -> str:
        """
        Save pending reminder data for confirmation.

        Returns:
            Confirmation ID
        """
        confirmation_id = str(uuid.uuid4())[:8]
        data = {
            "user_id": user_id,
            "template": template,
            "schedule_type": schedule_type,
            "time": time,
            "timezone": timezone,
            "weekday": weekday,
            "summary": summary,
        }
        key = self._make_key(confirmation_id)
        await self.redis.setex(key, self.ttl, json.dumps(data))
        logger.debug(f"Saved pending reminder confirmation {confirmation_id}")
        return confirmation_id

    async def get_pending(self, confirmation_id: str) -> dict[str, Any] | None:
        """Get pending reminder data by confirmation ID."""
        key = self._make_key(confirmation_id)
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def delete_pending(self, confirmation_id: str) -> bool:
        """Delete pending confirmation."""
        key = self._make_key(confirmation_id)
        result = await self.redis.delete(key)
        return bool(result)
