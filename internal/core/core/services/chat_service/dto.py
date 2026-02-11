"""DTOs for chat service."""

from dataclasses import dataclass


@dataclass
class ChatResult:
    content: str
    type: str = "text"  # "text" | "auth_required"
