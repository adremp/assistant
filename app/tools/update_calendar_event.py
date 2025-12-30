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
        "Обновить существующее событие в Google Calendar. "
        "Используй для изменения названия, времени или описания события."
    )
    parameters = {
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "ID события для обновления",
            },
            "summary": {
                "type": "string",
                "description": "Новое название события",
            },
            "start_time": {
                "type": "string",
                "description": "Новое время начала в формате ISO 8601 с часовым поясом",
            },
            "end_time": {
                "type": "string",
                "description": "Новое время окончания в формате ISO 8601 с часовым поясом",
            },
            "description": {
                "type": "string",
                "description": "Новое описание события",
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
                "message": "Пользователь не авторизован. Попроси выполнить /auth",
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
                "message": f"Событие '{event.get('summary')}' обновлено.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Ошибка при обновлении события: {str(e)}",
            }
