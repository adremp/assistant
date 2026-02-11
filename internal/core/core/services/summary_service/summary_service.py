"""Summary service - CRUD for summary groups + background scheduler."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot

from core.config import Settings
from core.repository.mcp_repo import MCPRepository
from pkg.summary_group_storage import SummaryGroupStorage

logger = logging.getLogger(__name__)


class SummaryService:
    def __init__(
        self,
        storage: SummaryGroupStorage,
        mcp_repo: MCPRepository,
        bot: Bot,
        settings: Settings,
    ):
        self.storage = storage
        self.mcp_repo = mcp_repo
        self.bot = bot
        self.settings = settings
        self._running = False

    # ── CRUD ──────────────────────────────────────────────────────────

    async def create_group(
        self,
        user_id: int,
        name: str,
        prompt: str,
        channel_ids: list[str],
        interval_hours: int = 6,
    ) -> str:
        return await self.storage.create_group(
            user_id, name, prompt, channel_ids, interval_hours
        )

    async def get_user_groups(self, user_id: int) -> list[dict[str, Any]]:
        return await self.storage.get_user_groups(user_id)

    async def get_group(self, group_id: str) -> dict[str, Any] | None:
        return await self.storage.get_group(group_id)

    async def delete_group(self, group_id: str) -> bool:
        return await self.storage.delete_group(group_id)

    async def add_channel(self, group_id: str, channel_id: str) -> bool:
        return await self.storage.add_channel(group_id, channel_id)

    async def remove_channel(self, group_id: str, channel_id: str) -> bool:
        return await self.storage.remove_channel(group_id, channel_id)

    async def update_interval(self, group_id: str, interval_hours: int) -> bool:
        return await self.storage.update_interval(group_id, interval_hours)

    async def get_available_chats(self, user_id: int) -> list[dict]:
        result = await self.mcp_repo.call_tool(
            "get_user_chats", {"user_id": user_id}
        )
        if result.get("success"):
            return result.get("chats", [])
        return []

    # ── Scheduler ─────────────────────────────────────────────────────

    async def start(self):
        """Start the background scheduler loop."""
        self._running = True
        logger.info("SummaryService scheduler started")
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                self._running = False
                break
            except Exception as e:
                logger.error(f"SummaryService tick error: {e}", exc_info=True)
            await asyncio.sleep(60)

    async def _tick(self):
        """Check all groups and process those that are due."""
        groups = await self.storage.get_all_groups()
        now = datetime.now(timezone.utc)

        for group in groups:
            try:
                interval_hours = group.get("interval_hours", 6)
                last_check = group.get("last_check_at")

                if last_check:
                    last_check_dt = datetime.fromisoformat(last_check)
                    if last_check_dt.tzinfo is None:
                        last_check_dt = last_check_dt.replace(tzinfo=timezone.utc)
                    elapsed = (now - last_check_dt).total_seconds()
                    if elapsed < interval_hours * 3600:
                        continue

                await self._process_group(group)
            except Exception as e:
                logger.error(
                    f"Error processing summary group {group.get('id')}: {e}",
                    exc_info=True,
                )

    async def _process_group(self, group: dict):
        """Process a single group: generate summary and send to user."""
        group_id = group["id"]
        user_id = group["user_id"]
        channel_ids = group.get("channel_ids", [])
        prompt = group.get("prompt", "")
        last_message_ids = group.get("last_message_ids", {})

        if not channel_ids:
            logger.info(f"Summary group {group_id}: no channels, skipping")
            return

        logger.info(f"Processing summary group {group_id} for user {user_id}")

        result = await self.mcp_repo.call_tool(
            "generate_summary",
            {
                "user_id": user_id,
                "channel_ids": channel_ids,
                "prompt": prompt,
                "last_message_ids": last_message_ids,
            },
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        if not result.get("success", False):
            logger.warning(
                f"Summary group {group_id}: generation failed - {result.get('error')}"
            )
            await self.storage.update_last_check(group_id, now_iso, last_message_ids)
            return

        new_last_ids = result.get("last_message_ids", last_message_ids)
        await self.storage.update_last_check(group_id, now_iso, new_last_ids)

        summary = result.get("summary", "")
        if not summary:
            logger.info(f"Summary group {group_id}: empty summary")
            return

        group_name = group.get("name", "Без названия")
        text = f"\U0001f4cb Саммари \"{group_name}\"\n\n{summary}"

        if len(text) > 4096:
            text = text[:4090] + "\n..."

        try:
            await self.bot.send_message(user_id, text)
            logger.info(f"Sent summary for group {group_id} to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send summary to {user_id}: {e}")
