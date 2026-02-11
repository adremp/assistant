"""DTOs for tool registry."""

from dataclasses import dataclass


@dataclass
class ToolCallResult:
    success: bool
    data: str
    is_response: bool = False
    auth_required: bool = False
