"""Telethon client for accessing Telegram channel history."""

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, Message

from mcp_summaries.config import Settings

logger = logging.getLogger(__name__)


class TelethonRepo:
    """Repository for accessing Telegram channels via MTProto (per-user sessions)."""

    def __init__(self, settings: Settings, session_string: str | None = None):
        self.settings = settings
        self._client: TelegramClient | None = None
        self._session_string = session_string or ""

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.telethon_api_id and self.settings.telethon_api_hash)

    def get_session_string(self) -> str:
        if self._client:
            return self._client.session.save()
        return self._session_string

    async def get_client(self) -> TelegramClient | None:
        if not self.is_configured:
            logger.warning("Telethon not configured: missing api_id or api_hash")
            return None

        if self._client is None:
            session = StringSession(self._session_string)
            self._client = TelegramClient(
                session,
                self.settings.telethon_api_id,
                self.settings.telethon_api_hash,
            )

        if not self._client.is_connected():
            await self._client.connect()

        return self._client

    async def is_authorized(self) -> bool:
        client = await self.get_client()
        if client is None:
            return False
        return await client.is_user_authorized()

    async def send_code(self, phone: str) -> str:
        client = await self.get_client()
        if client is None:
            raise ValueError("Telethon not configured")
        result = await client.send_code_request(phone)
        return result.phone_code_hash

    async def sign_in(self, phone: str, code: str, phone_code_hash: str) -> str | None:
        client = await self.get_client()
        if client is None:
            raise ValueError("Telethon not configured")
        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            return self.get_session_string()
        except Exception as e:
            logger.error(f"Telethon sign_in failed: {e}")
            return None

    async def get_user_channels(self) -> list[dict]:
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            return []
        try:
            channels = []
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, (Channel, Chat)):
                    if isinstance(entity, Channel) or (
                        hasattr(entity, "megagroup") and entity.megagroup
                    ):
                        channels.append(
                            {
                                "id": entity.id,
                                "title": getattr(entity, "title", "Unknown"),
                                "username": getattr(entity, "username", None),
                            }
                        )
            return channels
        except Exception as e:
            logger.error(f"Failed to get user channels: {e}")
            return []

    async def get_channel_info(self, channel_id: str) -> dict | None:
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            return None
        try:
            entity = await client.get_entity(channel_id)
            if isinstance(entity, (Channel, Chat)):
                return {
                    "id": entity.id,
                    "title": getattr(entity, "title", "Unknown"),
                    "username": getattr(entity, "username", None),
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get channel {channel_id}: {e}")
            return None

    async def get_channel_messages(
        self,
        channel_id: str,
        limit: int = 1000,
    ) -> list[dict]:
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            return []
        try:
            entity = await client.get_entity(channel_id)
            messages = []
            async for message in client.iter_messages(entity, limit=limit):
                if isinstance(message, Message) and message.text:
                    sender_name = "Unknown"
                    if message.sender:
                        sender_name = getattr(
                            message.sender,
                            "first_name",
                            getattr(message.sender, "title", "Unknown"),
                        )
                    messages.append(
                        {
                            "sender": sender_name,
                            "text": message.text,
                            "date": message.date.isoformat() if message.date else None,
                        }
                    )
            messages.reverse()
            return messages
        except Exception as e:
            logger.error(f"Failed to get messages from {channel_id}: {e}")
            return []

    async def get_channel_messages_formatted(
        self,
        channel_id: str,
        limit: int = 1000,
    ) -> str:
        messages = await self.get_channel_messages(channel_id, limit)
        lines = []
        for msg in messages:
            sender = msg.get("sender", "?")
            text = msg.get("text", "").replace("\n", " ")
            lines.append(f"{sender}: {text}")
        return "\n".join(lines)

    async def get_user_chats(self) -> list[dict]:
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            return []
        try:
            chats = []
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, Channel):
                    chat_type = (
                        "group" if getattr(entity, "megagroup", False) else "channel"
                    )
                    chats.append(
                        {
                            "id": entity.id,
                            "title": getattr(entity, "title", "Unknown"),
                            "username": getattr(entity, "username", None),
                            "type": chat_type,
                        }
                    )
                elif isinstance(entity, Chat):
                    chats.append(
                        {
                            "id": entity.id,
                            "title": getattr(entity, "title", "Unknown"),
                            "username": None,
                            "type": "group",
                        }
                    )
            return chats
        except Exception as e:
            logger.error(f"Failed to get user chats: {e}")
            return []

    async def get_messages_since(
        self,
        chat_id: str,
        min_id: int = 0,
        limit: int = 500,
    ) -> list[dict]:
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            return []
        try:
            entity = await client.get_entity(chat_id)
            chat_title = getattr(entity, "title", str(chat_id))
            messages = []
            async for message in client.iter_messages(
                entity, limit=limit, min_id=min_id
            ):
                if isinstance(message, Message) and message.text:
                    sender_name = "Unknown"
                    if message.sender:
                        sender_name = getattr(
                            message.sender,
                            "first_name",
                            getattr(message.sender, "title", "Unknown"),
                        )
                    messages.append(
                        {
                            "id": message.id,
                            "sender": sender_name,
                            "text": message.text,
                            "date": message.date.isoformat() if message.date else None,
                            "chat_title": chat_title,
                        }
                    )
            messages.reverse()
            return messages
        except Exception as e:
            logger.error(f"Failed to get messages since {min_id} from {chat_id}: {e}")
            return []

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected():
            await self._client.disconnect()
