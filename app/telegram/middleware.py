"""Telegram middleware for logging and rate limiting."""

import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Middleware for logging all incoming messages with deduplication."""

    def __init__(self):
        """Initialize with message ID tracking."""
        # Store recent message IDs to prevent duplicates
        self._processed_messages: deque = deque(maxlen=1000)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Log incoming message and measure processing time.

        Args:
            handler: Next handler in chain
            event: Telegram event
            data: Handler data

        Returns:
            Handler result
        """
        if isinstance(event, Message):
            # Check for duplicate message
            message_id = event.message_id
            chat_id = event.chat.id
            unique_id = f"{chat_id}:{message_id}"
            
            if unique_id in self._processed_messages:
                logger.debug(f"Skipping duplicate message {unique_id}")
                return None
            
            self._processed_messages.append(unique_id)
            
            user = event.from_user
            user_id = user.id if user else 0
            username = user.username if user else "unknown"
            text = event.text[:50] if event.text else "<no text>"

            logger.info(
                f"Message from {username} (ID: {user_id}): {text}"
            )

            start_time = time.monotonic()
            result = await handler(event, data)
            elapsed = time.monotonic() - start_time

            logger.debug(
                f"Processed message from {user_id} in {elapsed:.2f}s"
            )
            return result

        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Middleware for rate limiting users."""

    def __init__(
        self,
        rate_limit: float = 1.0,
        max_requests: int = 30,
        window: int = 60,
    ):
        """
        Initialize rate limiter.

        Args:
            rate_limit: Minimum seconds between messages
            max_requests: Maximum requests per window
            window: Window size in seconds
        """
        self.rate_limit = rate_limit
        self.max_requests = max_requests
        self.window = window
        self._user_timestamps: Dict[int, list[float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Check rate limits before processing.

        Args:
            handler: Next handler in chain
            event: Telegram event
            data: Handler data

        Returns:
            Handler result or rate limit message
        """
        if not isinstance(event, Message):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        user_id = user.id
        current_time = time.monotonic()

        # Get user's request history
        timestamps = self._user_timestamps.get(user_id, [])
        
        # Remove old timestamps outside the window
        cutoff = current_time - self.window
        timestamps = [t for t in timestamps if t > cutoff]

        # Check rate limit
        if timestamps:
            time_since_last = current_time - timestamps[-1]
            if time_since_last < self.rate_limit:
                logger.warning(f"Rate limit (fast): user {user_id}")
                return None  # Silently drop

            if len(timestamps) >= self.max_requests:
                logger.warning(f"Rate limit (max): user {user_id}")
                await event.answer(
                    "⚠️ Слишком много запросов. Подождите немного."
                )
                return None

        # Record this request
        timestamps.append(current_time)
        self._user_timestamps[user_id] = timestamps

        return await handler(event, data)
