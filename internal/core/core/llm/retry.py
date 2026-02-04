"""Retry handler with exponential backoff for LLM API calls."""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

from openai import RateLimitError, APITimeoutError, APIConnectionError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RateLimitException(Exception):
    """Exception raised when rate limit is hit and user should be notified."""
    
    def __init__(self, message: str, retry_after: float = 30.0):
        super().__init__(message)
        self.retry_after = retry_after


class RetryHandler:
    """Handles retries with exponential backoff for API calls."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        rate_limit_delay: float = 30.0,
    ):
        """
        Initialize retry handler.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds for exponential backoff
            max_delay: Maximum delay in seconds
            rate_limit_delay: Delay for rate limit errors (to notify user)
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.rate_limit_delay = rate_limit_delay

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        *args,
        **kwargs,
    ) -> T:
        """
        Execute a function with retry logic.

        Args:
            func: Async function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the function call

        Raises:
            RateLimitException: When rate limit hit (to notify user)
            Exception: The last exception if all retries fail
        """
        last_exception: Exception | None = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except RateLimitError as e:
                last_exception = e
                delay = self._get_rate_limit_delay(e)
                logger.warning(
                    f"Rate limit hit, need to wait {delay:.1f}s "
                    f"(attempt {attempt + 1}/{self.max_retries + 1})"
                )
                # Raise special exception to notify user
                raise RateLimitException(
                    "Превышен лимит запросов. Подождите немного...",
                    retry_after=delay,
                )
            except (APITimeoutError, APIConnectionError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        f"API error: {e}, retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.max_retries + 1})"
                    )
                    await asyncio.sleep(delay)
            except Exception as e:
                # Don't retry on other exceptions
                logger.error(f"Non-retryable error: {e}")
                raise

        # All retries exhausted
        logger.error(f"All {self.max_retries + 1} attempts failed")
        raise last_exception  # type: ignore

    def _get_rate_limit_delay(self, error: RateLimitError) -> float:
        """Get delay from rate limit error or use default."""
        response = getattr(error, "response", None)
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(float(retry_after), self.max_delay)
                except ValueError:
                    pass
        return self.rate_limit_delay

    def _calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for the next retry.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)
        return min(delay, self.max_delay)

