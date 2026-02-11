"""DTOs for conversation repository."""

from dataclasses import dataclass, field


@dataclass
class ConversationMessage:
    role: str
    content: str
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
