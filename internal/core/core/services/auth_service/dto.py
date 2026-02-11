"""DTOs for auth service."""

from dataclasses import dataclass


@dataclass
class AuthResult:
    success: bool
    user_id: int | None = None
    error: str | None = None
