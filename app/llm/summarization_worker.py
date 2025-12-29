"""Background worker for conversation summarization using Redis keyspace notifications."""

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from redis.asyncio import Redis

if TYPE_CHECKING:
    from app.llm.client import LLMClient

logger = logging.getLogger(__name__)

# TTL marker prefix - when this expires, we summarize
TTL_MARKER_PREFIX = "conversation_ttl:"
CONVERSATION_PREFIX = "conversation:"


class SummarizationWorker:
    """Background worker that listens for expired conversations and summarizes them."""

    def __init__(self, redis: Redis, llm_client: "LLMClient"):
        """
        Initialize the summarization worker.

        Args:
            redis: Redis client instance
            llm_client: LLM client for summarization
        """
        self.redis = redis
        self.llm_client = llm_client
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background worker."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Summarization worker started")

    async def stop(self) -> None:
        """Stop the background worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Summarization worker stopped")

    async def _run(self) -> None:
        """Main worker loop - subscribe to keyspace notifications."""
        # Create a separate connection for pubsub
        pubsub = self.redis.pubsub()

        # Subscribe to expired events for our TTL markers
        # Pattern: __keyevent@0__:expired matches all expired keys in DB 0
        await pubsub.psubscribe("__keyevent@*__:expired")
        
        logger.info("Subscribed to Redis keyspace notifications")

        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0
                    )
                    
                    if message and message["type"] == "pmessage":
                        key = message["data"]
                        if isinstance(key, bytes):
                            key = key.decode("utf-8")
                        
                        # Check if this is our TTL marker
                        if key.startswith(TTL_MARKER_PREFIX):
                            user_id = int(key.replace(TTL_MARKER_PREFIX, ""))
                            logger.info(f"TTL expired for user {user_id}, summarizing...")
                            await self._summarize_conversation(user_id)
                            
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await asyncio.sleep(1)
                    
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    async def _summarize_conversation(self, user_id: int) -> None:
        """
        Summarize and replace conversation for a user.

        Args:
            user_id: User ID whose conversation expired
        """
        try:
            # Get conversation data (stored without TTL)
            conversation_key = f"{CONVERSATION_PREFIX}{user_id}"
            data = await self.redis.get(conversation_key)
            
            if not data:
                logger.debug(f"No conversation data for user {user_id}")
                return
            
            history = json.loads(data)
            
            # Filter out system messages for summarization
            messages = [msg for msg in history if msg.get("role") != "system"]
            
            if len(messages) < 2:
                # Not enough to summarize, just delete
                await self.redis.delete(conversation_key)
                logger.debug(f"Deleted empty conversation for user {user_id}")
                return
            
            # Format messages for summarization
            conversation_text = "\n".join([
                f"{msg.get('role', 'unknown')}: {msg.get('content', '')[:500]}"
                for msg in messages[-20:]
            ])
            
            # Get summary from LLM
            summary = await self._get_summary(conversation_text)
            
            # Keep system message and add summary
            system_msg = next((msg for msg in history if msg.get("role") == "system"), None)
            new_history = []
            if system_msg:
                new_history.append(system_msg)
            new_history.append({
                "role": "assistant",
                "content": f"[Краткое содержание предыдущего диалога]\n{summary}"
            })
            
            # Save new history (no TTL - will be set when user sends message)
            await self.redis.set(conversation_key, json.dumps(new_history))
            logger.info(f"Summarized conversation for user {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to summarize conversation for user {user_id}: {e}")

    async def _get_summary(self, conversation_text: str) -> str:
        """
        Get summary from LLM.

        Args:
            conversation_text: Text to summarize

        Returns:
            Summary text
        """
        try:
            response = await self.llm_client.client.chat.completions.create(
                model=self.llm_client.settings.llm_model,
                messages=[
                    {"role": "system", "content": "Кратко суммаризируй диалог в 2-3 предложениях на русском. Укажи основные темы и результаты."},
                    {"role": "user", "content": f"Суммаризируй:\n\n{conversation_text}"}
                ],
                temperature=0.3,
                max_tokens=200,
            )
            return response.choices[0].message.content or "Предыдущий диалог."
        except Exception as e:
            logger.error(f"LLM summarization failed: {e}")
            return "Предыдущий диалог был суммаризирован."
