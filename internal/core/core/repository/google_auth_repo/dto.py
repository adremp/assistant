"""DTOs for Google auth repository."""

from dataclasses import dataclass


@dataclass
class AuthCredentials:
    token: str
    refresh_token: str | None
    expiry: str | None
