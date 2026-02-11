"""Watcher scheduler - periodically checks watchers and sends filtered messages."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from aiogram import Bot
from redis.asyncio import Redis

from core.config import Settings
from core.mcp_client.manager import MCPClientManager
from pkg.watcher_storage import WatcherStorage

_langfuse_host = os.getenv("LANGFUSE_HOST", "")
if _langfuse_host:
    from langfuse.openai import AsyncOpenAI
else:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

LLM_FILTER_SYSTEM_PROMPT = """Ты фильтр сообщений. Получаешь список сообщений и критерий поиска.
Верни JSON-массив номеров сообщений, которые соответствуют критерию.
Если ни одно не подходит — верни пустой массив [].
Ответь ТОЛЬКО JSON-массивом номеров, без пояснений."""


class WatcherScheduler:
    def __init__(
        self,
        bot: Bot,
        mcp_manager: MCPClientManager,
        settings: Settings,
        redis: Redis,
    ):
        self.bot = bot
        self.mcp_manager = mcp_manager
        self.settings = settings
        self.redis = redis
        self._running = False

    async def start(self):
        """Start the background scheduler loop."""
        self._running = True
        logger.info("WatcherScheduler started")
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                self._running = False
                break
            except Exception as e:
                logger.error(f"WatcherScheduler tick error: {e}", exc_info=True)
            await asyncio.sleep(self.settings.watcher_check_interval_seconds)

    async def _tick(self):
        """Check all watchers and process those that are due."""
        storage = WatcherStorage(self.redis)
        watchers = await storage.get_all_watchers()

        now = datetime.now(timezone.utc)

        for watcher in watchers:
            try:
                last_check = watcher.get("last_check_at")
                interval = watcher.get("interval_seconds", 10800)

                if last_check:
                    last_check_dt = datetime.fromisoformat(last_check)
                    if last_check_dt.tzinfo is None:
                        last_check_dt = last_check_dt.replace(tzinfo=timezone.utc)
                    elapsed = (now - last_check_dt).total_seconds()
                    if elapsed < interval:
                        continue

                await self._process_watcher(watcher)
            except Exception as e:
                logger.error(
                    f"Error processing watcher {watcher.get('id')}: {e}",
                    exc_info=True,
                )

    async def _process_watcher(self, watcher: dict):
        """Process a single watcher: fetch messages, filter, send results."""
        watcher_id = watcher["id"]
        user_id = watcher["user_id"]
        chat_ids = watcher.get("chat_ids", [])
        last_message_ids = watcher.get("last_message_ids", {})
        prompt = watcher.get("prompt", "")

        logger.info(f"Processing watcher {watcher_id} for user {user_id}")

        # Fetch new messages via MCP tool
        result = await self.mcp_manager.call_tool(
            "fetch_new_chat_messages",
            {
                "user_id": user_id,
                "chat_ids": chat_ids,
                "last_message_ids": last_message_ids,
            },
        )

        if not result.get("success", False):
            logger.warning(f"Watcher {watcher_id}: fetch failed - {result.get('error')}")
            return

        messages = result.get("messages", [])
        new_last_ids = result.get("last_message_ids", last_message_ids)

        # Update last_check and last_message_ids regardless of messages
        storage = WatcherStorage(self.redis)
        await storage.update_last_check(
            watcher_id,
            last_check_at=datetime.now(timezone.utc).isoformat(),
            last_message_ids=new_last_ids,
        )

        if not messages:
            logger.info(f"Watcher {watcher_id}: no new messages")
            return

        # Filter messages through LLM
        filtered = await self._filter_messages_with_llm(messages, prompt)

        if not filtered:
            logger.info(f"Watcher {watcher_id}: no messages matched the prompt")
            return

        # Send results to user
        await self._send_results(user_id, watcher.get("name", "Unnamed"), filtered)

    async def _filter_messages_with_llm(
        self, messages: list[dict], prompt: str
    ) -> list[dict]:
        """Filter messages using LLM based on the watcher prompt.
        Splits into batches to stay within TPM limits."""
        if not messages:
            return []

        # Build lines for each message
        msg_lines = []
        for msg in messages:
            chat_title = msg.get("chat_title", "?")
            sender = msg.get("sender", "?")
            text = msg.get("text", "").replace("\n", " ")
            date = msg.get("date", "")
            msg_lines.append(f"[{chat_title}] {sender}: {text} ({date})")

        # Split into batches (~4 chars per token, keep under 5000 tokens per batch)
        max_chars_per_batch = 16000
        batches: list[list[int]] = []  # list of [original_index, ...]
        current_batch: list[int] = []
        current_chars = 0

        for i, line in enumerate(msg_lines):
            line_chars = len(line)
            if current_chars + line_chars > max_chars_per_batch and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(i)
            current_chars += line_chars

        if current_batch:
            batches.append(current_batch)

        logger.info(f"Filtering {len(messages)} messages in {len(batches)} batches")

        client = AsyncOpenAI(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_base_url,
            timeout=self.settings.llm_timeout,
        )

        filtered = []
        for batch_indices in batches:
            batch_result = await self._filter_batch(
                client, messages, msg_lines, batch_indices, prompt
            )
            filtered.extend(batch_result)

        return filtered

    async def _filter_batch(
        self,
        client: AsyncOpenAI,
        messages: list[dict],
        msg_lines: list[str],
        batch_indices: list[int],
        prompt: str,
    ) -> list[dict]:
        """Filter a single batch of messages through LLM."""
        lines = []
        for num, idx in enumerate(batch_indices, 1):
            lines.append(f"{num}. {msg_lines[idx]}")

        user_content = f"Критерий: {prompt}\n\nСообщения:\n" + "\n".join(lines)
        user_content += "\n\nОтветь ТОЛЬКО JSON-массивом номеров: [1, 3, 5]"

        try:
            response = await client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": LLM_FILTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
            )

            content = response.choices[0].message.content or "[]"
            content = content.strip()
            if not content.startswith("["):
                start = content.find("[")
                end = content.rfind("]")
                if start != -1 and end != -1:
                    content = content[start : end + 1]
                else:
                    return []

            indices = json.loads(content)
            if not isinstance(indices, list):
                return []

            # Map 1-based batch numbers back to original messages
            filtered = []
            for num in indices:
                if isinstance(num, int) and 1 <= num <= len(batch_indices):
                    original_idx = batch_indices[num - 1]
                    filtered.append(messages[original_idx])

            return filtered

        except Exception as e:
            logger.error(f"LLM filter batch error: {e}", exc_info=True)
            return []

    async def _send_results(
        self, user_id: int, watcher_name: str, messages: list[dict]
    ):
        """Send filtered messages to user via Bot."""
        parts = [f"🔍 Мониторинг \"{watcher_name}\"\nНайдено {len(messages)} сообщений:\n"]

        for msg in messages:
            chat_title = msg.get("chat_title", "?")
            sender = msg.get("sender", "?")
            text = msg.get("text", "")
            date = msg.get("date", "")
            parts.append(f"📌 [{chat_title}] {sender}: {text}\n   {date}")

        text = "\n\n".join(parts)

        # Telegram message limit is 4096 chars
        if len(text) > 4096:
            text = text[:4090] + "\n..."

        try:
            await self.bot.send_message(user_id, text)
            logger.info(f"Sent {len(messages)} watcher results to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send watcher results to {user_id}: {e}")
