"""DTOs for telegram handler."""

from dataclasses import dataclass


@dataclass
class ChatRequest:
    user_id: int
    text: str


@dataclass
class ChatResponse:
    text: str
    type: str = "text"  # "text" | "auth_required"


@dataclass
class VoiceRequest:
    user_id: int
    audio_data: bytes
    filename: str
