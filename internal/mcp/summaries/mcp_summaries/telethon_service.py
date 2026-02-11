"""Telethon client for accessing Telegram channel history."""

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, Message

from mcp_summaries.config import Settings

logger = logging.getLogger(__name__)


class TelethonService:
    """Service for accessing Telegram channels via MTProto (per-user sessions)."""

    def __init__(self, settings: Settings, session_string: str | None = None):
        """
        Initialize Telethon service.

        Args:
            settings: Application settings with API credentials
            session_string: Optional existing session string for user
        """
        self.settings = settings
        self._client: TelegramClient | None = None
        self._session_string = session_string or ""

    @property
    def is_configured(self) -> bool:
        """Check if Telethon is configured with API credentials."""
        return bool(self.settings.telethon_api_id and self.settings.telethon_api_hash)

    def get_session_string(self) -> str:
        """Get current session string (for saving to user storage)."""
        if self._client:
            return self._client.session.save()
        return self._session_string

    async def get_client(self) -> TelegramClient | None:
        """
        Get or create Telethon client with StringSession.

        Returns:
            TelegramClient instance or None if not configured
        """
        if not self.is_configured:
            logger.warning("Telethon not configured: missing api_id or api_hash")
            return None

        if self._client is None:
            # Use StringSession for per-user sessions (stored in Redis)
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
        """Check if user is authorized in Telethon."""
        client = await self.get_client()
        if client is None:
            return False
        return await client.is_user_authorized()

    async def send_code(self, phone: str) -> str:
        """
        Send authorization code to phone.

        Args:
            phone: Phone number with country code

        Returns:
            Phone code hash for verification
        """
        client = await self.get_client()
        if client is None:
            raise ValueError("Telethon not configured")

        result = await client.send_code_request(phone)
        return result.phone_code_hash

    async def sign_in(self, phone: str, code: str, phone_code_hash: str) -> str | None:
        """
        Complete authorization with code.

        Args:
            phone: Phone number
            code: Received SMS code
            phone_code_hash: Hash from send_code

        Returns:
            Session string if successful, None otherwise
        """
        client = await self.get_client()
        if client is None:
            raise ValueError("Telethon not configured")

        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            # Return session string to save
            return self.get_session_string()
        except Exception as e:
            logger.error(f"Telethon sign_in failed: {e}")
            return None

    async def get_user_channels(self) -> list[dict]:
        """
        Get all channels the user is subscribed to.

        Returns:
            List of channel dicts with id, title, username
        """
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            return []

        try:
            channels = []
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, (Channel, Chat)):
                    # Only include channels/supergroups, not regular chats
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
            logger.info(f"Found {len(channels)} channels for user")
            return channels
        except Exception as e:
            logger.error(f"Failed to get user channels: {e}")
            return []

    async def get_channel_info(self, channel_id: str) -> dict | None:
        """
        Get channel information.

        Args:
            channel_id: Channel username (without @) or ID

        Returns:
            Channel info dict or None
        """
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
        """
        Get messages from a channel.

        Args:
            channel_id: Channel username (without @) or ID
            limit: Maximum number of messages to fetch

        Returns:
            List of message dicts with sender and text
        """
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            logger.warning("Cannot fetch messages: not authorized")
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

            # Reverse to get chronological order
            messages.reverse()
            logger.info(f"Fetched {len(messages)} messages from {channel_id}")
            return messages

        except Exception as e:
            logger.error(f"Failed to get messages from {channel_id}: {e}")
            return []

    async def get_channel_messages_formatted(
        self,
        channel_id: str,
        limit: int = 1000,
    ) -> str:
        """
        Get messages from a channel in token-optimized format.

        Format: "sender: message" per line (saves tokens vs JSON).

        Args:
            channel_id: Channel username (without @) or ID
            limit: Maximum number of messages

        Returns:
            Formatted string with all messages
        """
        messages = await self.get_channel_messages(channel_id, limit)

        lines = []
        for msg in messages:
            sender = msg.get("sender", "?")
            text = msg.get("text", "").replace("\n", " ")  # Flatten multiline
            lines.append(f"{sender}: {text}")

        return "\n".join(lines)

    async def get_user_chats(self) -> list[dict]:
        """
        Get all channels and groups the user is part of.

        Returns:
            List of chat dicts with id, title, username, type
        """
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            return []

        try:
            chats = []
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, Channel):
                    chat_type = "group" if getattr(entity, "megagroup", False) else "channel"
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
            logger.info(f"Found {len(chats)} chats for user")
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
        """
        Get messages from a chat with ID > min_id.

        Args:
            chat_id: Channel/group username or ID
            min_id: Minimum message ID (fetch messages after this)
            limit: Maximum number of messages to fetch

        Returns:
            List of message dicts with id, sender, text, date, chat_title
        """
        client = await self.get_client()
        if client is None or not await self.is_authorized():
            return []

        try:
            entity = await client.get_entity(chat_id)
            chat_title = getattr(entity, "title", str(chat_id))
            messages = []

            async for message in client.iter_messages(entity, limit=limit, min_id=min_id):
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
            logger.info(f"Fetched {len(messages)} new messages from {chat_id} (min_id={min_id})")
            return messages

        except Exception as e:
            logger.error(f"Failed to get messages since {min_id} from {chat_id}: {e}")
            return []

    async def disconnect(self) -> None:
        """Disconnect Telethon client."""
        if self._client and self._client.is_connected():
            await self._client.disconnect()
            logger.info("Telethon disconnected")
