"""Summary group storage using Redis."""

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
        self.redis = redis
        self._prefix = "summary_group"
        self._user_index_prefix = "user_summary_groups"

    def _make_key(self, group_id: str) -> str:
        return f"{self._prefix}:{group_id}"

    def _make_user_index_key(self, user_id: int) -> str:
        return f"{self._user_index_prefix}:{user_id}"

    async def create_group(
        self,
        user_id: int,
        name: str,
        prompt: str,
        channel_ids: list[str],
        interval_hours: int = 6,
    ) -> str:
        group_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        group_data = {
            "id": group_id,
            "user_id": user_id,
            "name": name,
            "prompt": prompt,
            "channel_ids": channel_ids,
            "interval_hours": interval_hours,
            "last_check_at": None,
            "last_message_ids": {},
            "created_at": now,
            "updated_at": now,
        }

        key = self._make_key(group_id)
        await self.redis.set(key, json.dumps(group_data))

        user_key = self._make_user_index_key(user_id)
        await self.redis.sadd(user_key, group_id)

        logger.info(f"Created summary group {group_id} for user {user_id}")
        return group_id

    async def get_group(self, group_id: str) -> dict[str, Any] | None:
        key = self._make_key(group_id)
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def get_user_groups(self, user_id: int) -> list[dict[str, Any]]:
        user_key = self._make_user_index_key(user_id)
        group_ids = await self.redis.smembers(user_key)

        groups = []
        for group_id in group_ids:
            group_id_str = group_id.decode() if isinstance(group_id, bytes) else group_id
            group = await self.get_group(group_id_str)
            if group:
                groups.append(group)

        groups.sort(key=lambda g: g.get("created_at", ""), reverse=True)
        return groups

    async def get_all_groups(self) -> list[dict[str, Any]]:
        pattern = f"{self._prefix}:*"
        groups = []
        async for key in self.redis.scan_iter(match=pattern):
            data = await self.redis.get(key)
            if data:
                groups.append(json.loads(data))
        return groups

    async def delete_group(self, group_id: str) -> bool:
        group = await self.get_group(group_id)
        if group is None:
            return False

        key = self._make_key(group_id)
        await self.redis.delete(key)

        user_id = group.get("user_id")
        if user_id:
            user_key = self._make_user_index_key(user_id)
            await self.redis.srem(user_key, group_id)

        logger.info(f"Deleted summary group {group_id}")
        return True

    async def add_channel(self, group_id: str, channel_id: str) -> bool:
        group = await self.get_group(group_id)
        if group is None:
            return False

        channels = group.get("channel_ids", [])
        if channel_id in channels:
            return False

        channels.append(channel_id)
        group["channel_ids"] = channels
        group["updated_at"] = datetime.now().isoformat()

        key = self._make_key(group_id)
        await self.redis.set(key, json.dumps(group))
        return True

    async def remove_channel(self, group_id: str, channel_id: str) -> bool:
        group = await self.get_group(group_id)
        if group is None:
            return False

        channels = group.get("channel_ids", [])
        if channel_id not in channels:
            return False

        channels.remove(channel_id)
        group["channel_ids"] = channels
        group["updated_at"] = datetime.now().isoformat()

        key = self._make_key(group_id)
        await self.redis.set(key, json.dumps(group))
        return True

    async def update_interval(self, group_id: str, interval_hours: int) -> bool:
        group = await self.get_group(group_id)
        if group is None:
            return False

        group["interval_hours"] = interval_hours
        group["updated_at"] = datetime.now().isoformat()

        key = self._make_key(group_id)
        await self.redis.set(key, json.dumps(group))
        return True

    async def update_last_check(
        self,
        group_id: str,
        last_check_at: str,
        last_message_ids: dict[str, int],
    ) -> bool:
        group = await self.get_group(group_id)
        if group is None:
            return False

        group["last_check_at"] = last_check_at
        group["last_message_ids"] = last_message_ids
        group["updated_at"] = datetime.now().isoformat()

        key = self._make_key(group_id)
        await self.redis.set(key, json.dumps(group))
        return True
