"""Conversation history storage using Redis with separate TTL markers."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

DEFAULT_TTL = 3 * 60 * 60


class ConversationRepository:
    """Redis-based storage for conversation history with TTL markers for background summarization."""

    def __init__(self, redis: Redis, ttl: int = DEFAULT_TTL):
        self.redis = redis
        self.ttl = ttl
        self._prefix = "conversation"
        self._ttl_marker_prefix = "conversation_ttl"

    def _make_key(self, user_id: int) -> str:
        return f"{self._prefix}:{user_id}"

    def _make_ttl_marker_key(self, user_id: int) -> str:
        return f"{self._ttl_marker_prefix}:{user_id}"

    async def _refresh_ttl_marker(self, user_id: int) -> None:
        key = self._make_ttl_marker_key(user_id)
        await self.redis.setex(key, self.ttl, "1")

    async def get(self, user_id: int) -> list[dict[str, Any]]:
        key = self._make_key(user_id)
        data = await self.redis.get(key)
        if data is None:
            return []
        return json.loads(data)

    async def get_for_summarization(self, user_id: int) -> list[dict[str, Any]]:
        history = await self.get(user_id)
        return [msg for msg in history if msg.get("role") != "system"]

    async def append(self, user_id: int, message: dict[str, Any]) -> None:
        history = await self.get(user_id)
        history.append(message)

        if len(history) > 50:
            history = history[-50:]

        key = self._make_key(user_id)
        await self.redis.set(key, json.dumps(history))
        await self._refresh_ttl_marker(user_id)

        logger.debug(f"Appended message for user {user_id}, history size: {len(history)}")

    async def append_many(self, user_id: int, messages: list[dict[str, Any]]) -> None:
        history = await self.get(user_id)
        history.extend(messages)

        if len(history) > 50:
            history = history[-50:]

        key = self._make_key(user_id)
        await self.redis.set(key, json.dumps(history))
        await self._refresh_ttl_marker(user_id)

        logger.debug(f"Appended {len(messages)} messages for user {user_id}")

    async def clear(self, user_id: int) -> None:
        key = self._make_key(user_id)
        ttl_key = self._make_ttl_marker_key(user_id)
        await self.redis.delete(key)
        await self.redis.delete(ttl_key)
        logger.debug(f"Cleared conversation history for user {user_id}")

    async def replace_with_summary(self, user_id: int, summary: str) -> None:
        history = await self.get(user_id)

        system_msg = None
        for msg in history:
            if msg.get("role") == "system":
                system_msg = msg
                break

        new_history = []
        if system_msg:
            new_history.append(system_msg)

        new_history.append({
            "role": "assistant",
            "content": f"[Краткое содержание предыдущего диалога]\n{summary}"
        })

        key = self._make_key(user_id)
        await self.redis.set(key, json.dumps(new_history))

        logger.info(f"Replaced history with summary for user {user_id}")

    async def set_system_message(self, user_id: int, content: str) -> None:
        history = await self.get(user_id)
        history = [msg for msg in history if msg.get("role") != "system"]
        history.insert(0, {"role": "system", "content": content})

        key = self._make_key(user_id)
        await self.redis.set(key, json.dumps(history))
        await self._refresh_ttl_marker(user_id)

        logger.debug(f"Set system message for user {user_id}")
