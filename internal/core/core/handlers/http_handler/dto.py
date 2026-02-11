"""DTOs for HTTP handler."""

from dataclasses import dataclass


@dataclass
class OAuthCallbackRequest:
    code: str
    state: str
