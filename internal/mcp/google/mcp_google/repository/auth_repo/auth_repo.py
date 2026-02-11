"""Google OAuth2 credentials reader (read-only from shared Redis)."""

import json
import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from pkg.token_storage import TokenStorage

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/tasks",
]


class AuthRepo:
    """Read-only Google credentials from shared Redis."""

    def __init__(self, token_storage: TokenStorage, credentials_path: Path):
        self.token_storage = token_storage
        self.credentials_path = credentials_path
        self._client_config: dict | None = None

    def _load_client_config(self) -> dict:
        if self._client_config is None:
            if not self.credentials_path.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {self.credentials_path}"
                )
            with open(self.credentials_path) as f:
                config = json.load(f)
            if "web" in config:
                self._client_config = config["web"]
            elif "installed" in config:
                self._client_config = config["installed"]
            else:
                self._client_config = config
        return self._client_config

    async def get_credentials(self, user_id: int) -> Credentials | None:
        token_data = await self.token_storage.load_token(user_id)
        if token_data is None:
            return None

        try:
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            logger.error(f"Failed to create credentials for user {user_id}: {e}")
            return None

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save refreshed token
                new_token_data = json.loads(creds.to_json())
                client_config = self._load_client_config()
                new_token_data["client_id"] = client_config.get("client_id")
                new_token_data["client_secret"] = client_config.get("client_secret")
                # Preserve non-OAuth fields (timezone, telethon_session, etc.)
                for key in token_data:
                    if key not in new_token_data:
                        new_token_data[key] = token_data[key]
                await self.token_storage.save_token(user_id, new_token_data)
            except Exception as e:
                logger.error(f"Failed to refresh token for user {user_id}: {e}")
                return None

        return creds
