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
        "Создать новое событие в Google Calendar пользователя. "
        "Используй этот инструмент когда пользователь хочет добавить встречу, "
        "напоминание или событие в календарь."
    )
    parameters = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Название события",
            },
            "start_time": {
                "type": "string",
                "description": (
                    "Время начала события в формате ISO 8601 "
                    "(например: 2024-01-15T09:00:00+05:00)"
                ),
            },
            "end_time": {
                "type": "string",
                "description": (
                    "Время окончания события в формате ISO 8601 "
                    "(например: 2024-01-15T10:00:00+05:00)"
                ),
            },
            "description": {
                "type": "string",
                "description": "Описание события (опционально)",
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        credentials = await self.auth_service.get_credentials(user_id)
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": (
                    "Пользователь не авторизован в Google. "
                    "Попроси пользователя выполнить команду /auth для авторизации."
                ),
            }

        try:
            event = await self.calendar_service.create_event(
                credentials=credentials,
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
            )

            return {
                "success": True,
                "event": event,
                "message": f"Событие '{summary}' успешно создано.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Ошибка при создании события: {str(e)}",
            }
