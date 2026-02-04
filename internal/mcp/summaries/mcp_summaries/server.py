"""MCP Summaries server - Telegram channel summaries via Telethon."""

import json
import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pkg.token_storage import TokenStorage
from redis.asyncio import Redis

from mcp_summaries.config import get_settings
from mcp_summaries.storage.summary_groups import SummaryGroupStorage
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
    token_storage = TokenStorage(redis, settings.token_ttl_seconds)
    session_string = await token_storage.get_telethon_session(user_id)
    service = TelethonService(settings, session_string)

    if not service.is_configured:
        return _err("Telethon not configured (missing API credentials)")

    try:
        phone_code_hash = await service.send_code(phone)
        # Store auth state in Redis temporarily
        await redis.setex(
            f"telethon_auth:{user_id}",
            300,
            json.dumps({"phone": phone, "phone_code_hash": phone_code_hash}),
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
    session_string = await token_storage.get_telethon_session(user_id)
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


if __name__ == "__main__":
    import uvicorn

    # Get the HTTP ASGI app and run with uvicorn to bind to 0.0.0.0
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
