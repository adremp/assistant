"""Tool: Create calendar event in Google Calendar."""

from typing import Any

from app.tools.base import BaseTool
from app.google.calendar import CalendarService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.config import get_settings


class CreateCalendarEventTool(BaseTool):
    """Tool to create a new event in Google Calendar."""

    name = "create_calendar_event"
    description = (
        "Create a new event in user's Google Calendar. "
        "Use this tool when user wants to add a meeting, reminder or event to calendar. "
    )
    parameters = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Short description of the event",
            },
            "start_time": {
                "type": "string",
                "description": (
                    "Event start time in ISO 8601 format "
                    "(e.g., 2024-01-15T09:00:00+05:00)"
                ),
            },
            "end_time": {
                "type": "string",
                "description": (
                    "Event end time in ISO 8601 format "
                    "(e.g., 2024-01-15T10:00:00+05:00)"
                ),
            },
            "description": {
                "type": "string",
                "description": "Event description (optional)",
            },
            "freq": {
                "type": "string",
                "enum": ["once", "daily", "weekly", "monthly", "yearly"],
                "description": (
                    "Event frequency: 'once' for single event, "
                    "'daily', 'weekly', 'monthly', or 'yearly' for recurring"
                ),
            },
            "freq_days": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"],
                },
                "description": "Days of week for weekly recurring events",
            },
        },
        "required": ["summary", "start_time", "end_time"],
    }

    def __init__(self, token_storage: TokenStorage):
        self.token_storage = token_storage
        self.calendar_service = CalendarService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        summary: str,
        start_time: str,
        end_time: str,
        description: str | None = None,
        freq: str | None = None,
        freq_days: list[str] | None = None,
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
            settings = get_settings()
            
            # Build recurrence rule from freq and freq_days
            recurrence: list[str] | None = None
            if freq and freq != "once":
                freq_upper = freq.upper()
                if freq == "weekly" and freq_days:
                    days_str = ",".join(freq_days)
                    recurrence = [f"RRULE:FREQ={freq_upper};BYDAY={days_str}"]
                else:
                    recurrence = [f"RRULE:FREQ={freq_upper}"]
            
            event = await self.calendar_service.create_event(
                credentials=credentials,
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
                recurrence=recurrence,
                timezone=settings.default_timezone if recurrence else None,
            )

            recurrence_msg = ""
            if recurrence:
                recurrence_msg = f" (recurring: {freq}"
                if freq_days:
                    recurrence_msg += f", days: {', '.join(freq_days)}"
                recurrence_msg += ")"

            return {
                "success": True,
                "event": event,
                "message": f"Event '{summary}' created successfully{recurrence_msg}.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Error creating event: {str(e)}",
            }

