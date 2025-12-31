"""Tool: Update calendar event."""

import logging
from typing import Any

from app.tools.base import BaseTool
from app.google.calendar import CalendarService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.config import get_settings

logger = logging.getLogger(__name__)


class UpdateCalendarEventTool(BaseTool):
    """Tool to update an existing calendar event."""

    name = "update_calendar_event"
    description = (
        "Update an existing event in Google Calendar. "
        "Use this tool to change event title, time or description."
    )
    parameters = {
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "ID of the event to update",
            },
            "summary": {
                "type": "string",
                "description": "New event title",
            },
            "start_time": {
                "type": "string",
                "description": "New start time in ISO 8601 format with timezone",
            },
            "end_time": {
                "type": "string",
                "description": "New end time in ISO 8601 format with timezone",
            },
            "description": {
                "type": "string",
                "description": "New event description",
            },
        },
        "required": ["event_id"],
    }

    def __init__(self, token_storage: TokenStorage):
        self.token_storage = token_storage
        self.calendar_service = CalendarService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        event_id: str,
        summary: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        credentials = await self.auth_service.get_credentials(user_id)
        
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": "User is not authorized. Ask user to run /auth command.",
            }

        try:
            event = await self.calendar_service.update_event(
                credentials=credentials,
                event_id=event_id,
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
            )

            return {
                "success": True,
                "event": event,
                "message": f"Event '{event.get('summary')}' updated.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Error updating event: {str(e)}",
            }
