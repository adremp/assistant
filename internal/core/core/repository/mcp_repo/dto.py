"""DTOs for MCP repository."""

from dataclasses import dataclass


@dataclass
class MCPToolSchema:
    name: str
    description: str
    parameters: dict
