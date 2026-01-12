"""Tool: Create reminder as recurring Google Calendar event."""

import logging
from typing import Any

from app.tools.base import BaseTool
from app.google.calendar import CalendarService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.storage.pending_reminder_confirm import PendingReminderConfirmation
from app.config import get_settings

logger = logging.getLogger(__name__)


class CreateReminderTool(BaseTool):
    """Tool to create a recurring reminder stored in Google Calendar."""

    name = "create_reminder"
    description = (
        "Create a recurring reminder for the user. "
        "Use this when user wants to be reminded about something daily or weekly. "
        "The reminder will be saved as a recurring Google Calendar event and "
        "send a message template to the user at the specified time. "
        "This tool returns a confirmation request - the user must confirm before creation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": (
                    "Template message to send as reminder. This is the question "
                    "or prompt that will be sent to the user at the scheduled time. "
                    "Examples: 'Как прошёл твой день?', 'Сколько часов ты сегодня работал?'"
                ),
            },
            "schedule_type": {
                "type": "string",
                "enum": ["daily", "weekly"],
                "description": "How often to send the reminder: 'daily' or 'weekly'",
            },
            "time": {
                "type": "string",
                "description": (
                    "Time to send reminder in HH:MM format (24-hour). "
                    "Example: '20:00' for 8 PM"
                ),
            },
            "weekday": {
                "type": "integer",
                "description": (
                    "Day of week for weekly reminders (0=Monday, 1=Tuesday, ..., 6=Sunday). "
                    "Only required when schedule_type is 'weekly'."
                ),
            },
            "summary": {
                "type": "string",
                "description": "Short title for the reminder (optional, defaults to first words of template)",
            },
        },
        "required": ["template", "schedule_type", "time"],
    }

    def __init__(
        self,
        token_storage: TokenStorage,
        pending_confirm: PendingReminderConfirmation,
    ):
        """Initialize with required services."""
        self.token_storage = token_storage
        self.pending_confirm = pending_confirm
        self.calendar_service = CalendarService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        template: str,
        schedule_type: str,
        time: str,
        weekday: int | None = None,
        summary: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        logger.info(
            f"create_reminder called for user_id={user_id}, "
            f"template={template[:30]}..., schedule_type={schedule_type}, time={time}"
        )

        # Validate schedule type
        if schedule_type not in ("daily", "weekly"):
            return {
                "success": False,
                "error": "invalid_schedule_type",
                "message": f"Invalid schedule type: {schedule_type}. Use 'daily' or 'weekly'.",
            }

        # Validate weekly requires weekday
        if schedule_type == "weekly" and weekday is None:
            return {
                "success": False,
                "error": "missing_weekday",
                "message": "Weekly reminders require a weekday (0-6).",
            }

        # Validate time format
        try:
            hour, minute = map(int, time.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time range")
        except (ValueError, AttributeError):
            return {
                "success": False,
                "error": "invalid_time",
                "message": f"Invalid time format: {time}. Use HH:MM format (e.g., '20:00').",
            }

        # Check Google auth
        credentials = await self.auth_service.get_credentials(user_id)
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": "User is not authorized in Google. Ask user to run /auth command.",
            }

        # Get user timezone
        timezone = await self.calendar_service.get_user_timezone(credentials)
        if not timezone:
            return {
                "success": False,
                "error": "no_timezone",
                "message": "Не удалось получить часовой пояс из Google Calendar. Повтори авторизацию /auth.",
            }

        await self.token_storage.set_user_timezone(user_id, timezone)

        # Save pending confirmation
        confirmation_id = await self.pending_confirm.save_pending(
            user_id=user_id,
            template=template,
            schedule_type=schedule_type,
            time=time,
            timezone=timezone,
            weekday=weekday,
            summary=summary,
        )

        weekdays = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
        
        if schedule_type == "daily":
            schedule_desc = f"ежедневно в {time}"
        else:
            day_name = weekdays[weekday] if weekday is not None else "?"
            schedule_desc = f"каждый {day_name} в {time}"

        return {
            "success": True,
            "needs_confirmation": True,
            "confirmation_id": confirmation_id,
            "schedule_description": schedule_desc,
            "timezone": timezone,
            "template": template,
            "message": (
                f"Подтвердите создание напоминания:\n\n"
                f"📝 Текст: {template}\n"
                f"⏰ Расписание: {schedule_desc}\n"
                f"🌍 Часовой пояс: {timezone}\n\n"
                f"Нажмите кнопку для подтверждения."
            ),
        }
