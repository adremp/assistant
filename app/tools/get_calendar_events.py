"""Tool: Get calendar events from Google Calendar."""

from typing import Any

from app.tools.base import BaseTool
from app.google.calendar import CalendarService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.config import get_settings


class GetCalendarEventsTool(BaseTool):
    """Tool to get upcoming events from Google Calendar."""

    name = "get_calendar_events"
    description = (
        "Get upcoming events from user's Google Calendar. "
        "Use this tool when user asks about their events, meetings, schedule or calendar."
    )
    parameters = {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events to return (default 10)",
                "default": 10,
            },
            "time_min": {
                "type": "string",
                "description": (
                    "Start of search period in ISO 8601 format (e.g., 2024-01-15T09:00:00Z). "
                    "Default is current time."
                ),
            },
        },
        "required": [],
    }

    def __init__(self, token_storage: TokenStorage):
        self.token_storage = token_storage
        self.calendar_service = CalendarService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        max_results: int = 10,
        time_min: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        credentials = await self.auth_service.get_credentials(user_id)
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": "User is not authorized in Google. Ask user to run /auth command.",
            }

        try:
            events = await self.calendar_service.list_events(
                credentials=credentials,
                max_results=max_results,
                time_min=time_min,
            )

            if not events:
                return {
                    "success": True,
                    "events": [],
                    "message": "No upcoming events in calendar.",
                }

            return {
                "success": True,
                "events": events,
                "count": len(events),
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Error getting events: {str(e)}",
            }
