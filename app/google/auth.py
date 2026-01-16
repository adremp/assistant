"""Google OAuth2 authentication service."""

import json
import logging
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

from app.config import Settings
from app.storage.tokens import TokenStorage

logger = logging.getLogger(__name__)


class GoogleAuthService:
    """Service for Google OAuth2 authentication with web redirect."""

    SCOPES = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/tasks.readonly",
        "https://www.googleapis.com/auth/tasks",
    ]

    def __init__(self, settings: Settings, token_storage: TokenStorage):
        """
        Initialize Google auth service.

        Args:
            settings: Application settings
            token_storage: Redis-based token storage
        """
        self.settings = settings
        self.token_storage = token_storage
        self._client_config: dict | None = None

    def _load_client_config(self) -> dict:
        """Load and cache client config from credentials file."""
        if self._client_config is None:
            credentials_path = self.settings.google_credentials_path
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {credentials_path}"
                )
            with open(credentials_path) as f:
                config = json.load(f)
            # Handle both web and installed app credentials
            if "web" in config:
                self._client_config = config["web"]
            elif "installed" in config:
                self._client_config = config["installed"]
            else:
                self._client_config = config
        return self._client_config

    @property
    def redirect_uri(self) -> str:
        """Get redirect URI for OAuth callback."""
        if not self.settings.google_redirect_uri:
            raise ValueError("GOOGLE_REDIRECT_URI not configured")
        return self.settings.google_redirect_uri

    def _create_flow(self) -> Flow:
        """Create a new OAuth2 flow."""
        credentials_path = self.settings.google_credentials_path

        if not credentials_path.exists():
            raise FileNotFoundError(
                f"Google credentials file not found: {credentials_path}"
            )

        return Flow.from_client_secrets_file(
            str(credentials_path),
            scopes=self.SCOPES,
            redirect_uri=self.redirect_uri,
        )

    async def get_credentials(self, user_id: int) -> Credentials | None:
        """
        Get valid credentials for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            Valid Credentials or None if not authorized
        """
        logger.info(f"Getting credentials for user {user_id}")
        token_data = await self.token_storage.load_token(user_id)
        if token_data is None:
            logger.info(f"No token found in Redis for user {user_id}")
            return None

        logger.info(f"Token found for user {user_id}, keys: {list(token_data.keys())}")
        
        try:
            creds = Credentials.from_authorized_user_info(token_data, self.SCOPES)
            logger.info(f"Credentials created for user {user_id}, valid={creds.valid}, expired={creds.expired}")
        except Exception as e:
            logger.error(f"Failed to create credentials from token for user {user_id}: {e}")
            return None

        # Check if credentials need refresh
        if creds.expired and creds.refresh_token:
            try:
                logger.info(f"Refreshing expired token for user {user_id}")
                creds.refresh(Request())
                # Save refreshed token with client info
                await self._save_credentials(user_id, creds)
                logger.info(f"Refreshed token for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh token for user {user_id}: {e}")
                await self.token_storage.delete_token(user_id)
                return None

        return creds

    async def _save_credentials(self, user_id: int, creds: Credentials) -> None:
        """
        Save credentials to Redis with client info for later restoration.

        Args:
            user_id: Telegram user ID
            creds: Google credentials
        """
        # Get base token data
        token_data = json.loads(creds.to_json())
        
        # Add client_id and client_secret (required for from_authorized_user_info)
        client_config = self._load_client_config()
        token_data["client_id"] = client_config.get("client_id")
        token_data["client_secret"] = client_config.get("client_secret")
        
        await self.token_storage.save_token(user_id, token_data)

    async def get_auth_url(self, user_id: int) -> str:
        """
        Generate authorization URL for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            Authorization URL for the user to visit
        """
        flow = self._create_flow()

        # Include state with user_id for callback identification
        state = str(user_id)

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )

        logger.debug(f"Generated auth URL for user {user_id}")
        return auth_url

    async def handle_callback(self, code: str, state: str | None = None) -> tuple[bool, int | None]:
        """
        Handle OAuth2 callback with authorization code.

        Args:
            code: Authorization code from callback
            state: State parameter containing user_id

        Returns:
            Tuple of (success, user_id)
        """
        try:
            # Extract user_id from state
            user_id = int(state) if state else None
            if user_id is None:
                logger.error("No user_id in OAuth state")
                return False, None

            # Create a fresh flow and exchange code for token
            flow = self._create_flow()
            flow.fetch_token(code=code)
            creds = flow.credentials

            # Save token to Redis with client info
            await self._save_credentials(user_id, creds)
            logger.info(f"User {user_id} authorized successfully")
            return True, user_id

        except Exception as e:
            logger.error(f"Failed to handle callback: {e}")
            return False, None

    async def revoke_access(self, user_id: int) -> bool:
        """
        Revoke user's access and delete stored token.

        Args:
            user_id: Telegram user ID

        Returns:
            True if revoked successfully
        """
        await self.token_storage.delete_token(user_id)
        logger.info(f"Revoked access for user {user_id}")
        return True

    async def is_authorized(self, user_id: int) -> bool:
        """
        Check if user is authorized.

        Args:
            user_id: Telegram user ID

        Returns:
            True if user has valid credentials
        """
        creds = await self.get_credentials(user_id)
        return creds is not None
