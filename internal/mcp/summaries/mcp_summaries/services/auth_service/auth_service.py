"""Telethon authentication service."""

import json
import logging

from pkg.token_storage import TokenStorage
from redis.asyncio import Redis

from mcp_summaries.config import Settings
from mcp_summaries.repository.telethon_repo import TelethonRepo

logger = logging.getLogger(__name__)


class AuthService:
    """Orchestrates Telethon authentication flow."""

    def __init__(self, settings: Settings, redis: Redis, token_storage: TokenStorage):
        self.settings = settings
        self.redis = redis
        self.token_storage = token_storage

    async def start_auth(self, user_id: int, phone: str) -> dict:
        """Send auth code to phone. Returns result dict."""
        # Clear previous auth state and use empty session
        await self.redis.delete(f"telethon_auth:{user_id}")
        repo = TelethonRepo(self.settings, None)

        try:
            phone_code_hash = await repo.send_code(phone)
            await self.redis.setex(
                f"telethon_auth:{user_id}",
                300,
                json.dumps(
                    {
                        "phone": phone,
                        "phone_code_hash": phone_code_hash,
                        "session_string": repo.get_session_string(),
                    }
                ),
            )
            return {
                "message": "Code sent to phone. Use telethon_auth_submit_code to complete."
            }
        finally:
            await repo.disconnect()

    async def submit_code(self, user_id: int, code: str) -> dict:
        """Submit auth code. Returns result dict or raises."""
        code = "".join(c for c in code if c.isdigit())

        auth_data = await self.redis.get(f"telethon_auth:{user_id}")
        if not auth_data:
            raise ValueError("No pending auth. Start again with telethon_auth_start.")

        auth_info = json.loads(auth_data)
        session_string = auth_info.get("session_string")
        repo = TelethonRepo(self.settings, session_string)

        try:
            new_session = await repo.sign_in(
                auth_info["phone"], code, auth_info["phone_code_hash"]
            )
            if new_session:
                await self.token_storage.set_telethon_session(user_id, new_session)
                await self.redis.delete(f"telethon_auth:{user_id}")
                return {"message": "Telethon authenticated successfully."}
            raise ValueError("Authentication failed. Try again.")
        finally:
            await repo.disconnect()
