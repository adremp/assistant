"""Google OAuth2 repository - credential storage and OAuth flow management."""

import json
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from pkg.token_storage import TokenStorage

from core.config import Settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/tasks",
]


class GoogleAuthRepository:
    """Handles Google OAuth2 credential persistence and token exchange."""

    def __init__(self, settings: Settings, token_storage: TokenStorage):
        self.settings = settings
        self.token_storage = token_storage
        self._client_config: dict | None = None

    def _load_client_config(self) -> dict:
        if self._client_config is None:
            credentials_path = self.settings.google_credentials_path
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {credentials_path}"
                )
            with open(credentials_path) as f:
                config = json.load(f)
            if "web" in config:
                self._client_config = config["web"]
            elif "installed" in config:
                self._client_config = config["installed"]
            else:
                self._client_config = config
        return self._client_config

    @property
    def redirect_uri(self) -> str:
        if not self.settings.google_redirect_uri:
            raise ValueError("GOOGLE_REDIRECT_URI not configured")
        return self.settings.google_redirect_uri

    def _create_flow(self) -> Flow:
        credentials_path = self.settings.google_credentials_path
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"Google credentials file not found: {credentials_path}"
            )
        return Flow.from_client_secrets_file(
            str(credentials_path),
            scopes=SCOPES,
            redirect_uri=self.redirect_uri,
        )

    async def get_credentials(self, user_id: int) -> Credentials | None:
        """Get valid credentials for a user, refreshing if needed."""
        logger.info(f"Getting credentials for user {user_id}")
        token_data = await self.token_storage.load_token(user_id)
        if token_data is None:
            logger.info(f"No token found in Redis for user {user_id}")
            return None

        logger.info(f"Token found for user {user_id}, keys: {list(token_data.keys())}")

        try:
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            logger.info(
                f"Credentials created for user {user_id}, valid={creds.valid}, expired={creds.expired}"
            )
        except Exception as e:
            logger.error(
                f"Failed to create credentials from token for user {user_id}: {e}"
            )
            return None

        if creds.expired and creds.refresh_token:
            try:
                logger.info(f"Refreshing expired token for user {user_id}")
                creds.refresh(Request())
                await self._save_credentials(user_id, creds)
                logger.info(f"Refreshed token for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh token for user {user_id}: {e}")
                await self.token_storage.delete_token(user_id)
                return None

        return creds

    async def _save_credentials(self, user_id: int, creds: Credentials) -> None:
        token_data = json.loads(creds.to_json())
        client_config = self._load_client_config()
        token_data["client_id"] = client_config.get("client_id")
        token_data["client_secret"] = client_config.get("client_secret")
        await self.token_storage.save_token(user_id, token_data)

    async def create_auth_url(self, user_id: int) -> str:
        """Generate authorization URL for a user."""
        flow = self._create_flow()
        state = str(user_id)
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        logger.debug(f"Generated auth URL for user {user_id}")
        return auth_url

    async def exchange_code(self, code: str, state: str | None = None) -> tuple[bool, int | None]:
        """Exchange authorization code for tokens and save."""
        try:
            user_id = int(state) if state else None
            if user_id is None:
                logger.error("No user_id in OAuth state")
                return False, None

            flow = self._create_flow()
            flow.fetch_token(code=code)
            creds = flow.credentials

            await self._save_credentials(user_id, creds)
            logger.info(f"User {user_id} authorized successfully")
            return True, user_id

        except Exception as e:
            logger.error(f"Failed to handle callback: {e}")
            return False, None

    async def delete_credentials(self, user_id: int) -> None:
        await self.token_storage.delete_token(user_id)
        logger.info(f"Deleted credentials for user {user_id}")
