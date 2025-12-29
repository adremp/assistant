"""Conversation history storage using Redis with separate TTL markers."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# 3 hours in seconds
DEFAULT_TTL = 3 * 60 * 60


class ConversationHistory:
    """Redis-based storage for conversation history with TTL markers for background summarization."""

    def __init__(self, redis: Redis, ttl: int = DEFAULT_TTL):
        """
        Initialize conversation history storage.

        Args:
            redis: Redis client instance
            ttl: History time-to-live in seconds (default: 3 hours)
        """
        self.redis = redis
        self.ttl = ttl
        self._prefix = "conversation"
        self._ttl_marker_prefix = "conversation_ttl"

    def _make_key(self, user_id: int) -> str:
        """Generate Redis key for user's conversation."""
        return f"{self._prefix}:{user_id}"

    def _make_ttl_marker_key(self, user_id: int) -> str:
        """Generate Redis key for TTL marker (triggers background summarization on expire)."""
        return f"{self._ttl_marker_prefix}:{user_id}"

    async def _refresh_ttl_marker(self, user_id: int) -> None:
        """
        Refresh the TTL marker for a user.
        When this marker expires, the background worker will summarize the conversation.
        """
        key = self._make_ttl_marker_key(user_id)
        await self.redis.setex(key, self.ttl, "1")

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

    async def get_for_summarization(self, user_id: int) -> list[dict[str, Any]]:
        """
        Get conversation history for summarization (excluding system message).

        Args:
            user_id: Telegram user ID

        Returns:
            List of message dictionaries without system message
        """
        history = await self.get(user_id)
        return [msg for msg in history if msg.get("role") != "system"]

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
        # Store data WITHOUT TTL - background worker will handle cleanup
        await self.redis.set(key, json.dumps(history))
        
        # Refresh TTL marker (resets the 3-hour timer)
        await self._refresh_ttl_marker(user_id)
        
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
        await self.redis.set(key, json.dumps(history))
        
        # Refresh TTL marker
        await self._refresh_ttl_marker(user_id)
        
        logger.debug(f"Appended {len(messages)} messages for user {user_id}")

    async def clear(self, user_id: int) -> None:
        """
        Clear conversation history for a user.

        Args:
            user_id: Telegram user ID
        """
        key = self._make_key(user_id)
        ttl_key = self._make_ttl_marker_key(user_id)
        await self.redis.delete(key)
        await self.redis.delete(ttl_key)
        logger.debug(f"Cleared conversation history for user {user_id}")

    async def replace_with_summary(self, user_id: int, summary: str) -> None:
        """
        Replace conversation history with a summary.

        Args:
            user_id: Telegram user ID
            summary: Summary of previous conversation
        """
        history = await self.get(user_id)
        
        # Keep system message if exists
        system_msg = None
        for msg in history:
            if msg.get("role") == "system":
                system_msg = msg
                break
        
        # Create new history with summary
        new_history = []
        if system_msg:
            new_history.append(system_msg)
        
        # Add summary as assistant message
        new_history.append({
            "role": "assistant",
            "content": f"[Краткое содержание предыдущего диалога]\n{summary}"
        })
        
        key = self._make_key(user_id)
        await self.redis.set(key, json.dumps(new_history))
        
        # Don't set TTL marker - will be set when user sends next message
        logger.info(f"Replaced history with summary for user {user_id}")

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
        await self.redis.set(key, json.dumps(history))
        
        # Refresh TTL marker
        await self._refresh_ttl_marker(user_id)
        
        logger.debug(f"Set system message for user {user_id}")
