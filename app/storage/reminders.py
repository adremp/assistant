"""Reminder storage using Redis."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ReminderStorage:
    """Redis-based storage for reminders."""

    def __init__(self, redis: Redis):
        """
        Initialize reminder storage.

        Args:
            redis: Redis client instance
        """
        self.redis = redis
        self._prefix = "reminder"
        self._user_index_prefix = "user_reminders"

    def _make_key(self, reminder_id: str) -> str:
        """Generate Redis key for a reminder."""
        return f"{self._prefix}:{reminder_id}"

    def _make_user_index_key(self, user_id: int) -> str:
        """Generate Redis key for user's reminder index."""
        return f"{self._user_index_prefix}:{user_id}"

    async def save_reminder(
        self,
        user_id: int,
        template: str,
        schedule_type: str,
        time: str,
        timezone: str,
        weekday: int | None = None,
        calendar_event_id: str | None = None,
    ) -> str:
        """
        Save a new reminder.

        Args:
            user_id: Telegram user ID
            template: Reminder message template
            schedule_type: "daily" or "weekly"
            time: Time in HH:MM format
            timezone: User's timezone (e.g., "Asia/Almaty")
            weekday: Day of week (0-6) for weekly reminders
            calendar_event_id: Google Calendar event ID

        Returns:
            Generated reminder ID
        """
        reminder_id = str(uuid.uuid4())
        reminder_data = {
            "id": reminder_id,
            "user_id": user_id,
            "template": template,
            "schedule_type": schedule_type,
            "time": time,
            "timezone": timezone,
            "weekday": weekday,
            "calendar_event_id": calendar_event_id,
            "created_at": datetime.now().isoformat(),
            "is_active": True,
        }

        # Save reminder data
        key = self._make_key(reminder_id)
        await self.redis.set(key, json.dumps(reminder_data))

        # Add to user's reminder index
        user_key = self._make_user_index_key(user_id)
        await self.redis.sadd(user_key, reminder_id)

        logger.info(f"Saved reminder {reminder_id} for user {user_id}")
        return reminder_id

    async def get_reminder(self, reminder_id: str) -> dict[str, Any] | None:
        """
        Get a reminder by ID.

        Args:
            reminder_id: Reminder ID

        Returns:
            Reminder data or None if not found
        """
        key = self._make_key(reminder_id)
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def get_reminders(self, user_id: int) -> list[dict[str, Any]]:
        """
        Get all reminders for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of reminder data dictionaries
        """
        user_key = self._make_user_index_key(user_id)
        reminder_ids = await self.redis.smembers(user_key)

        reminders = []
        for reminder_id in reminder_ids:
            reminder_id_str = reminder_id.decode() if isinstance(reminder_id, bytes) else reminder_id
            reminder = await self.get_reminder(reminder_id_str)
            if reminder and reminder.get("is_active", True):
                reminders.append(reminder)

        return reminders

    async def delete_reminder(self, reminder_id: str) -> bool:
        """
        Delete a reminder.

        Args:
            reminder_id: Reminder ID

        Returns:
            True if deleted, False if not found
        """
        # Get reminder to find user_id
        reminder = await self.get_reminder(reminder_id)
        if reminder is None:
            return False

        # Remove from main storage
        key = self._make_key(reminder_id)
        await self.redis.delete(key)

        # Remove from user's index
        user_id = reminder.get("user_id")
        if user_id:
            user_key = self._make_user_index_key(user_id)
            await self.redis.srem(user_key, reminder_id)

        logger.info(f"Deleted reminder {reminder_id}")
        return True

    async def get_all_active_reminders(self) -> list[dict[str, Any]]:
        """
        Get all active reminders across all users.
        Used for restoring schedules after restart.

        Returns:
            List of all active reminder data dictionaries
        """
        # Scan for all reminder keys
        reminders = []
        async for key in self.redis.scan_iter(f"{self._prefix}:*"):
            key_str = key.decode() if isinstance(key, bytes) else key
            data = await self.redis.get(key_str)
            if data:
                reminder = json.loads(data)
                if reminder.get("is_active", True):
                    reminders.append(reminder)

        return reminders

    async def delete_all_reminders(self) -> int:
        """
        Delete all reminders from storage.
        Used before full sync from Google Calendar.

        Returns:
            Number of deleted reminders
        """
        count = 0
        async for key in self.redis.scan_iter(f"{self._prefix}:*"):
            key_str = key.decode() if isinstance(key, bytes) else key
            # Get reminder to find user_id for index cleanup
            data = await self.redis.get(key_str)
            if data:
                reminder = json.loads(data)
                user_id = reminder.get("user_id")
                if user_id:
                    user_key = self._make_user_index_key(user_id)
                    reminder_id = reminder.get("id")
                    if reminder_id:
                        await self.redis.srem(user_key, reminder_id)
            await self.redis.delete(key_str)
            count += 1
        
        logger.info(f"Deleted all {count} reminders from storage")
        return count
