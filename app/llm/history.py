"""Conversation history storage using Redis."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ConversationHistory:
    """Redis-based storage for conversation history."""

    def __init__(self, redis: Redis, ttl: int = 86400):
        """
        Initialize conversation history storage.

        Args:
            redis: Redis client instance
            ttl: History time-to-live in seconds (default: 24 hours)
        """
        self.redis = redis
        self.ttl = ttl
        self._prefix = "conversation"

    def _make_key(self, user_id: int) -> str:
        """Generate Redis key for user's conversation."""
        return f"{self._prefix}:{user_id}"

    async def get(self, user_id: int) -> list[dict[str, Any]]:
        """
        Get conversation history for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of message dictionaries
        """
        key = self._make_key(user_id)
        data = await self.redis.get(key)
        if data is None:
            return []
        return json.loads(data)

    async def append(self, user_id: int, message: dict[str, Any]) -> None:
        """
        Append a message to conversation history.

        Args:
            user_id: Telegram user ID
            message: Message dictionary with role and content
        """
        history = await self.get(user_id)
        history.append(message)
        
        # Limit history to last 50 messages to prevent unbounded growth
        if len(history) > 50:
            history = history[-50:]
        
        key = self._make_key(user_id)
        await self.redis.setex(
            key,
            self.ttl,
            json.dumps(history),
        )
        logger.debug(f"Appended message for user {user_id}, history size: {len(history)}")

    async def append_many(self, user_id: int, messages: list[dict[str, Any]]) -> None:
        """
        Append multiple messages to conversation history.

        Args:
            user_id: Telegram user ID
            messages: List of message dictionaries
        """
        history = await self.get(user_id)
        history.extend(messages)
        
        # Limit history to last 50 messages
        if len(history) > 50:
            history = history[-50:]
        
        key = self._make_key(user_id)
        await self.redis.setex(
            key,
            self.ttl,
            json.dumps(history),
        )
        logger.debug(f"Appended {len(messages)} messages for user {user_id}")

    async def clear(self, user_id: int) -> None:
        """
        Clear conversation history for a user.

        Args:
            user_id: Telegram user ID
        """
        key = self._make_key(user_id)
        await self.redis.delete(key)
        logger.debug(f"Cleared conversation history for user {user_id}")

    async def set_system_message(self, user_id: int, content: str) -> None:
        """
        Set or update system message for the conversation.

        Args:
            user_id: Telegram user ID
            content: System message content
        """
        history = await self.get(user_id)
        
        # Remove existing system message if present
        history = [msg for msg in history if msg.get("role") != "system"]
        
        # Add new system message at the beginning
        history.insert(0, {"role": "system", "content": content})
        
        key = self._make_key(user_id)
        await self.redis.setex(
            key,
            self.ttl,
            json.dumps(history),
        )
        logger.debug(f"Set system message for user {user_id}")
