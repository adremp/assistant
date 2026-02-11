"""Watcher storage using Redis."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class WatcherStorage:
    """Redis-based storage for watchers."""

    def __init__(self, redis: Redis):
        self.redis = redis
        self._prefix = "watcher"
        self._user_index_prefix = "user_watchers"

    def _make_key(self, watcher_id: str) -> str:
        return f"{self._prefix}:{watcher_id}"

    def _make_user_index_key(self, user_id: int) -> str:
        return f"{self._user_index_prefix}:{user_id}"

    async def create_watcher(
        self,
        user_id: int,
        name: str,
        prompt: str,
        chat_ids: list[str],
        interval_seconds: int = 10800,
    ) -> str:
        watcher_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        watcher_data = {
            "id": watcher_id,
            "user_id": user_id,
            "name": name,
            "prompt": prompt,
            "chat_ids": chat_ids,
            "interval_seconds": interval_seconds,
            "last_check_at": None,
            "last_message_ids": {},
            "created_at": now,
            "updated_at": now,
        }

        key = self._make_key(watcher_id)
        await self.redis.set(key, json.dumps(watcher_data))

        user_key = self._make_user_index_key(user_id)
        await self.redis.sadd(user_key, watcher_id)

        logger.info(f"Created watcher {watcher_id} for user {user_id}")
        return watcher_id

    async def get_watcher(self, watcher_id: str) -> dict[str, Any] | None:
        key = self._make_key(watcher_id)
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)

    async def get_user_watchers(self, user_id: int) -> list[dict[str, Any]]:
        user_key = self._make_user_index_key(user_id)
        watcher_ids = await self.redis.smembers(user_key)

        watchers = []
        for watcher_id in watcher_ids:
            watcher_id_str = watcher_id.decode() if isinstance(watcher_id, bytes) else watcher_id
            watcher = await self.get_watcher(watcher_id_str)
            if watcher:
                watchers.append(watcher)

        watchers.sort(key=lambda w: w.get("created_at", ""), reverse=True)
        return watchers

    async def get_all_watchers(self) -> list[dict[str, Any]]:
        pattern = f"{self._prefix}:*"
        watchers = []
        async for key in self.redis.scan_iter(match=pattern):
            data = await self.redis.get(key)
            if data:
                watchers.append(json.loads(data))
        return watchers

    async def update_watcher(self, watcher_id: str, **fields) -> bool:
        watcher = await self.get_watcher(watcher_id)
        if watcher is None:
            return False

        for field, value in fields.items():
            if value is not None:
                watcher[field] = value

        watcher["updated_at"] = datetime.now().isoformat()

        key = self._make_key(watcher_id)
        await self.redis.set(key, json.dumps(watcher))

        logger.info(f"Updated watcher {watcher_id}")
        return True

    async def delete_watcher(self, watcher_id: str) -> bool:
        watcher = await self.get_watcher(watcher_id)
        if watcher is None:
            return False

        key = self._make_key(watcher_id)
        await self.redis.delete(key)

        user_id = watcher.get("user_id")
        if user_id:
            user_key = self._make_user_index_key(user_id)
            await self.redis.srem(user_key, watcher_id)

        logger.info(f"Deleted watcher {watcher_id}")
        return True

    async def update_last_check(
        self,
        watcher_id: str,
        last_check_at: str,
        last_message_ids: dict[str, int],
    ) -> bool:
        watcher = await self.get_watcher(watcher_id)
        if watcher is None:
            return False

        watcher["last_check_at"] = last_check_at
        watcher["last_message_ids"] = last_message_ids
        watcher["updated_at"] = datetime.now().isoformat()

        key = self._make_key(watcher_id)
        await self.redis.set(key, json.dumps(watcher))
        return True
