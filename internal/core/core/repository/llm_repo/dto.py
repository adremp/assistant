"""DTOs for LLM repository."""

from dataclasses import dataclass


@dataclass
class ToolCallInfo:
    id: str
    name: str
    arguments: str


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallInfo] | None
