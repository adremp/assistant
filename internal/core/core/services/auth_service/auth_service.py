"""Auth service - Google OAuth2 business logic."""

import logging

from core.repository.google_auth_repo import GoogleAuthRepository

logger = logging.getLogger(__name__)


class AuthService:
    """Google OAuth2 business logic."""

    def __init__(self, google_auth_repo: GoogleAuthRepository):
        self.repo = google_auth_repo

    async def is_authorized(self, user_id: int) -> bool:
        creds = await self.repo.get_credentials(user_id)
        return creds is not None

    async def get_auth_url(self, user_id: int) -> str:
        return await self.repo.create_auth_url(user_id)

    async def handle_callback(self, code: str, state: str | None = None) -> tuple[bool, int | None]:
        return await self.repo.exchange_code(code, state)

    async def revoke_access(self, user_id: int) -> bool:
        await self.repo.delete_credentials(user_id)
        logger.info(f"Revoked access for user {user_id}")
        return True
