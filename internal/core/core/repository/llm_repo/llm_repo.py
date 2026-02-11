"""LLM repository - raw OpenAI API calls with retry logic."""

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, TypeVar

from openai import RateLimitError, APITimeoutError, APIConnectionError

from core.config import Settings

_langfuse_host = os.getenv("LANGFUSE_HOST", "")
if _langfuse_host:
    from langfuse.openai import AsyncOpenAI
else:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RateLimitException(Exception):
    """Exception raised when rate limit is hit and user should be notified."""

    def __init__(self, message: str, retry_after: float = 30.0):
        super().__init__(message)
        self.retry_after = retry_after


class _RetryHandler:
    """Handles retries with exponential backoff for API calls."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        rate_limit_delay: float = 30.0,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.rate_limit_delay = rate_limit_delay

    async def execute(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
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
                logger.error(f"Non-retryable error: {e}")
                raise

        logger.error(f"All {self.max_retries + 1} attempts failed")
        raise last_exception  # type: ignore

    def _get_rate_limit_delay(self, error: RateLimitError) -> float:
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
        delay = self.base_delay * (2 ** attempt)
        return min(delay, self.max_delay)


class LLMRepository:
    """Raw OpenAI-compatible API client with retry logic."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
        self._retry_handler = _RetryHandler(
            max_retries=settings.llm_max_retries,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> Any:
        """Call LLM API with retry logic. Returns raw API response."""
        temp = temperature if temperature is not None else self.settings.llm_temperature

        async def make_request():
            return await self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                tools=tools if tools else None,
                temperature=temp,
            )

        return await self._retry_handler.execute(make_request)
