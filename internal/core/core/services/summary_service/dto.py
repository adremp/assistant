"""DTOs for summary service."""

from dataclasses import dataclass, field


@dataclass
class CreateGroupRequest:
    user_id: int
    name: str
    prompt: str
    channel_ids: list[str]
    interval_hours: int = 6


@dataclass
class SummaryResult:
    success: bool
    summary: str = ""
    channels_processed: int = 0
    last_message_ids: dict[str, int] = field(default_factory=dict)
    error: str = ""
