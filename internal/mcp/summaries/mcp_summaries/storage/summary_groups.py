"""Summary groups storage using Redis."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class SummaryGroupStorage:
    """Redis-based storage for summary groups."""

    def __init__(self, redis: Redis):
        """
        Initialize summary group storage.

        Args:
            redis: Redis client instance
        """
        self.redis = redis
        self._prefix = "summary_group"
        self._user_index_prefix = "user_summary_groups"

    def _make_key(self, group_id: str) -> str:
        """Generate Redis key for a summary group."""
        return f"{self._prefix}:{group_id}"

    def _make_user_index_key(self, user_id: int) -> str:
        """Generate Redis key for user's summary group index."""
        return f"{self._user_index_prefix}:{user_id}"

    async def create_group(
        self,
        user_id: int,
        name: str,
        prompt: str,
        channel_ids: list[str] | None = None,
    ) -> str:
        """
        Create a new summary group.

        Args:
            user_id: Telegram user ID
            name: Group name
            prompt: Custom prompt for AI summarization
            channel_ids: List of channel usernames/IDs

        Returns:
            Generated group ID
        """
        group_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        group_data = {
            "id": group_id,
            "user_id": user_id,
            "name": name,
            "prompt": prompt,
            "channel_ids": channel_ids or [],
            "created_at": now,
            "updated_at": now,
        }

        # Save group data
        key = self._make_key(group_id)
        await self.redis.set(key, json.dumps(group_data))

        # Add to user's group index
        user_key = self._make_user_index_key(user_id)
        await self.redis.sadd(user_key, group_id)

        logger.info(f"Created summary group {group_id} for user {user_id}")
        return group_id

    async def get_group(self, group_id: str) -> dict[str, Any] | None:
        """
        Get a summary group by ID.

        Args:
            group_id: Group ID

        Returns:
            Group data or None if not found
        """
        key = self._make_key(group_id)
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def get_user_groups(self, user_id: int) -> list[dict[str, Any]]:
        """
        Get all summary groups for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of group data dictionaries
        """
        user_key = self._make_user_index_key(user_id)
        group_ids = await self.redis.smembers(user_key)

        groups = []
        for group_id in group_ids:
            group_id_str = group_id.decode() if isinstance(group_id, bytes) else group_id
            group = await self.get_group(group_id_str)
            if group:
                groups.append(group)

        # Sort by creation date (newest first)
        groups.sort(key=lambda g: g.get("created_at", ""), reverse=True)
        return groups

    async def update_group(
        self,
        group_id: str,
        name: str | None = None,
        prompt: str | None = None,
        channel_ids: list[str] | None = None,
    ) -> bool:
        """
        Update a summary group.

        Args:
            group_id: Group ID
            name: New group name (optional)
            prompt: New prompt (optional)
            channel_ids: New channel list (optional)

        Returns:
            True if updated, False if not found
        """
        group = await self.get_group(group_id)
        if group is None:
            return False

        if name is not None:
            group["name"] = name
        if prompt is not None:
            group["prompt"] = prompt
        if channel_ids is not None:
            group["channel_ids"] = channel_ids

        group["updated_at"] = datetime.now().isoformat()

        key = self._make_key(group_id)
        await self.redis.set(key, json.dumps(group))

        logger.info(f"Updated summary group {group_id}")
        return True

    async def delete_group(self, group_id: str) -> bool:
        """
        Delete a summary group.

        Args:
            group_id: Group ID

        Returns:
            True if deleted, False if not found
        """
        group = await self.get_group(group_id)
        if group is None:
            return False

        # Remove from main storage
        key = self._make_key(group_id)
        await self.redis.delete(key)

        # Remove from user's index
        user_id = group.get("user_id")
        if user_id:
            user_key = self._make_user_index_key(user_id)
            await self.redis.srem(user_key, group_id)

        logger.info(f"Deleted summary group {group_id}")
        return True

    async def add_channel(self, group_id: str, channel_id: str) -> bool:
        """
        Add a channel to a summary group.

        Args:
            group_id: Group ID
            channel_id: Channel username or ID

        Returns:
            True if added, False if not found or already exists
        """
        group = await self.get_group(group_id)
        if group is None:
            return False

        channels = group.get("channel_ids", [])
        if channel_id in channels:
            return False

        channels.append(channel_id)
        return await self.update_group(group_id, channel_ids=channels)

    async def remove_channel(self, group_id: str, channel_id: str) -> bool:
        """
        Remove a channel from a summary group.

        Args:
            group_id: Group ID
            channel_id: Channel username or ID

        Returns:
            True if removed, False if not found
        """
        group = await self.get_group(group_id)
        if group is None:
            return False

        channels = group.get("channel_ids", [])
        if channel_id not in channels:
            return False

        channels.remove(channel_id)
        return await self.update_group(group_id, channel_ids=channels)
