"""MCP tools for Telegram channel/chat access."""

from mcp.server.fastmcp import FastMCP

from mcp_summaries.container import create_user_telethon_repo
from mcp_summaries.handlers import _err, _ok


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_channels(user_id: int) -> str:
        """Get list of Telegram channels the user is subscribed to."""
        repo = await create_user_telethon_repo(user_id)
        if repo is None:
            return _err("Not authenticated in Telethon. Use telethon_auth_start first.")
        try:
            channels = await repo.get_user_channels()
            return _ok({"channels": channels, "count": len(channels)})
        except Exception as e:
            return _err(f"Failed to get channels: {e}")
        finally:
            await repo.disconnect()

    @mcp.tool()
    async def get_user_chats(user_id: int) -> str:
        """Get list of Telegram channels and groups the user is part of."""
        repo = await create_user_telethon_repo(user_id)
        if repo is None:
            return _err("Not authenticated in Telethon. Use telethon_auth_start first.")
        try:
            chats = await repo.get_user_chats()
            return _ok({"chats": chats, "count": len(chats)})
        except Exception as e:
            return _err(f"Failed to get chats: {e}")
        finally:
            await repo.disconnect()

    @mcp.tool()
    async def fetch_new_chat_messages(
        user_id: int,
        chat_ids: list[str],
        last_message_ids: dict[str, int] | None = None,
    ) -> str:
        """Fetch new messages from specified chats since last known message IDs."""
        repo = await create_user_telethon_repo(user_id)
        if repo is None:
            return _err("Not authenticated in Telethon. Use telethon_auth_start first.")

        last_message_ids = last_message_ids or {}
        try:
            all_messages = []
            new_last_ids = dict(last_message_ids)

            for chat_id in chat_ids:
                min_id = last_message_ids.get(str(chat_id), 0)
                if min_id == 0:
                    # First check: just record the latest message ID
                    latest = await repo.get_messages_since(
                        str(chat_id), min_id=0, limit=1
                    )
                    if latest:
                        new_last_ids[str(chat_id)] = max(m["id"] for m in latest)
                    continue
                messages = await repo.get_messages_since(str(chat_id), min_id=min_id)
                if messages:
                    all_messages.extend(messages)
                    max_id = max(m["id"] for m in messages)
                    new_last_ids[str(chat_id)] = max_id

            return _ok(
                {
                    "messages": all_messages,
                    "count": len(all_messages),
                    "last_message_ids": new_last_ids,
                }
            )
        except Exception as e:
            return _err(f"Failed to fetch messages: {e}")
        finally:
            await repo.disconnect()
