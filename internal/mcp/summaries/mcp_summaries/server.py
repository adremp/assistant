"""MCP Summaries server - Telegram channel summaries via Telethon."""

import json
import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pkg.token_storage import TokenStorage
from redis.asyncio import Redis

from mcp_summaries.config import get_settings
from mcp_summaries.storage.summary_groups import SummaryGroupStorage
from mcp_summaries.storage.watchers import WatcherStorage
from mcp_summaries.summary_generator import SummaryGenerator
from mcp_summaries.telethon_service import TelethonService

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Configure security settings to allow Docker hostnames
security_settings = TransportSecuritySettings(
    allowed_hosts=["mcp-summaries:8000", "localhost:8000", "127.0.0.1:8000", "*"]
)
mcp = FastMCP("summaries", transport_security=security_settings)
settings = get_settings()

_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url)
    return _redis


def _ok(data: dict) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"success": False, "error": msg}, ensure_ascii=False)


@mcp.tool()
async def telethon_auth_start(user_id: int, phone: str) -> str:
    """Start Telethon authentication by sending code to phone number. Phone format: +79001234567."""
    redis = await get_redis()

    # Always start fresh: clear previous auth state and use empty session
    # to get a new auth_key. Reusing old sessions causes Telegram to return
    # cached phone_code_hash for expired codes.
    await redis.delete(f"telethon_auth:{user_id}")
    service = TelethonService(settings, None)

    try:
        phone_code_hash = await service.send_code(phone)
        # Store auth state + session in temp key (not main token_storage,
        # so other tools like get_channels don't use this incomplete session)
        await redis.setex(
            f"telethon_auth:{user_id}",
            300,
            json.dumps({
                "phone": phone,
                "phone_code_hash": phone_code_hash,
                "session_string": service.get_session_string(),
            }),
        )
        return _ok(
            {
                "message": "Code sent to phone. Use telethon_auth_submit_code to complete."
            }
        )
    except Exception as e:
        return _err(f"Failed to send code: {e}")
    finally:
        await service.disconnect()


@mcp.tool()
async def telethon_auth_submit_code(user_id: int, code: str) -> str:
    """Submit the authentication code received via SMS/Telegram."""
    redis = await get_redis()
    token_storage = TokenStorage(redis, settings.token_ttl_seconds)

    auth_data = await redis.get(f"telethon_auth:{user_id}")
    if not auth_data:
        return _err("No pending auth. Start again with telethon_auth_start.")

    auth_info = json.loads(auth_data)
    # Use session from send_code (stored in temp key, not main token_storage)
    session_string = auth_info.get("session_string")
    service = TelethonService(settings, session_string)

    try:
        new_session = await service.sign_in(
            auth_info["phone"], code, auth_info["phone_code_hash"]
        )
        if new_session:
            await token_storage.set_telethon_session(user_id, new_session)
            await redis.delete(f"telethon_auth:{user_id}")
            return _ok({"message": "Telethon authenticated successfully."})
        return _err("Authentication failed. Try again.")
    except Exception as e:
        return _err(f"Sign-in failed: {e}")
    finally:
        await service.disconnect()


@mcp.tool()
async def get_channels(user_id: int) -> str:
    """Get list of Telegram channels the user is subscribed to."""
    redis = await get_redis()
    token_storage = TokenStorage(redis, settings.token_ttl_seconds)
    session_string = await token_storage.get_telethon_session(user_id)

    if not session_string:
        return _err("Not authenticated in Telethon. Use telethon_auth_start first.")

    service = TelethonService(settings, session_string)
    try:
        channels = await service.get_user_channels()
        return _ok({"channels": channels, "count": len(channels)})
    except Exception as e:
        return _err(f"Failed to get channels: {e}")
    finally:
        await service.disconnect()


@mcp.tool()
async def create_summary_group(
    user_id: int, name: str, prompt: str, channel_ids: list[str]
) -> str:
    """Create a new summary group for monitoring channels."""
    redis = await get_redis()
    storage = SummaryGroupStorage(redis)
    group_id = await storage.create_group(user_id, name, prompt, channel_ids)
    return _ok({"group_id": group_id, "message": f"Summary group '{name}' created."})


@mcp.tool()
async def list_summary_groups(user_id: int) -> str:
    """List user's summary groups."""
    redis = await get_redis()
    storage = SummaryGroupStorage(redis)
    groups = await storage.get_user_groups(user_id)
    return _ok({"groups": groups, "count": len(groups)})


@mcp.tool()
async def delete_summary_group(user_id: int, group_id: str) -> str:
    """Delete a summary group."""
    redis = await get_redis()
    storage = SummaryGroupStorage(redis)
    deleted = await storage.delete_group(group_id)
    if deleted:
        return _ok({"message": "Summary group deleted."})
    return _err("Group not found.")


@mcp.tool()
async def generate_summary(user_id: int, group_id: str) -> str:
    """Generate a summary for a summary group's channels. Fetches messages and creates AI summary."""
    redis = await get_redis()
    token_storage = TokenStorage(redis, settings.token_ttl_seconds)
    storage = SummaryGroupStorage(redis)

    group = await storage.get_group(group_id)
    if not group:
        return _err("Group not found.")

    session_string = await token_storage.get_telethon_session(user_id)
    if not session_string:
        return _err("Telethon not authenticated.")

    service = TelethonService(settings, session_string)
    try:
        channels_data = []
        for channel_id in group.get("channel_ids", []):
            info = await service.get_channel_info(channel_id)
            name = info.get("title", channel_id) if info else channel_id
            text = await service.get_channel_messages_formatted(channel_id, limit=500)
            if text:
                channels_data.append({"channel_name": name, "messages_text": text})

        if not channels_data:
            return _err("No messages found in any channel.")

        generator = SummaryGenerator(settings)
        summary = await generator.generate_multi_channel_summary(
            channels_data, group.get("prompt", "")
        )
        return _ok({"summary": summary, "channels_processed": len(channels_data)})
    except Exception as e:
        return _err(f"Summary generation failed: {e}")
    finally:
        await service.disconnect()


@mcp.tool()
async def create_watcher(
    user_id: int,
    name: str,
    prompt: str,
    chat_ids: list[str],
    interval_seconds: int = 10800,
) -> str:
    """Create a watcher for automatic Telegram chat monitoring. The watcher will periodically check specified chats and filter messages using the given prompt criteria."""
    redis = await get_redis()
    storage = WatcherStorage(redis)
    watcher_id = await storage.create_watcher(user_id, name, prompt, chat_ids, interval_seconds)
    return _ok({"watcher_id": watcher_id, "message": f"Watcher '{name}' created."})


@mcp.tool()
async def list_watchers(user_id: int) -> str:
    """List user's watchers for Telegram chat monitoring."""
    redis = await get_redis()
    storage = WatcherStorage(redis)
    watchers = await storage.get_user_watchers(user_id)
    return _ok({"watchers": watchers, "count": len(watchers)})


@mcp.tool()
async def delete_watcher(user_id: int, watcher_id: str) -> str:
    """Delete a watcher by ID."""
    redis = await get_redis()
    storage = WatcherStorage(redis)
    deleted = await storage.delete_watcher(watcher_id)
    if deleted:
        return _ok({"message": "Watcher deleted."})
    return _err("Watcher not found.")


@mcp.tool()
async def get_user_chats(user_id: int) -> str:
    """Get list of Telegram channels and groups the user is part of."""
    redis = await get_redis()
    token_storage = TokenStorage(redis, settings.token_ttl_seconds)
    session_string = await token_storage.get_telethon_session(user_id)

    if not session_string:
        return _err("Not authenticated in Telethon. Use telethon_auth_start first.")

    service = TelethonService(settings, session_string)
    try:
        chats = await service.get_user_chats()
        return _ok({"chats": chats, "count": len(chats)})
    except Exception as e:
        return _err(f"Failed to get chats: {e}")
    finally:
        await service.disconnect()


@mcp.tool()
async def fetch_new_chat_messages(
    user_id: int,
    chat_ids: list[str],
    last_message_ids: dict[str, int] | None = None,
) -> str:
    """Fetch new messages from specified chats since last known message IDs."""
    redis = await get_redis()
    token_storage = TokenStorage(redis, settings.token_ttl_seconds)
    session_string = await token_storage.get_telethon_session(user_id)

    if not session_string:
        return _err("Not authenticated in Telethon. Use telethon_auth_start first.")

    last_message_ids = last_message_ids or {}
    service = TelethonService(settings, session_string)
    try:
        all_messages = []
        new_last_ids = dict(last_message_ids)

        for chat_id in chat_ids:
            min_id = last_message_ids.get(str(chat_id), 0)
            messages = await service.get_messages_since(str(chat_id), min_id=min_id)
            if messages:
                all_messages.extend(messages)
                max_id = max(m["id"] for m in messages)
                new_last_ids[str(chat_id)] = max_id

        return _ok({
            "messages": all_messages,
            "count": len(all_messages),
            "last_message_ids": new_last_ids,
        })
    except Exception as e:
        return _err(f"Failed to fetch messages: {e}")
    finally:
        await service.disconnect()


if __name__ == "__main__":
    import uvicorn

    # Get the HTTP ASGI app and run with uvicorn to bind to 0.0.0.0
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
