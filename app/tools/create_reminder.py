"""Tool: Create reminder as recurring Google Calendar event."""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.tools.base import BaseTool
from app.google.calendar import CalendarService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.storage.reminders import ReminderStorage
from app.scheduler.service import ReminderScheduler
from app.config import get_settings
from app.constants import REMINDER_TAG

logger = logging.getLogger(__name__)


class CreateReminderTool(BaseTool):
    """Tool to create a recurring reminder stored in Google Calendar."""

    name = "create_reminder"
    description = (
        "Create a recurring reminder for the user. "
        "Use this when user wants to be reminded about something daily or weekly. "
        "The reminder will be saved as a recurring Google Calendar event and "
        "send a message template to the user at the specified time."
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
        reminder_storage: ReminderStorage,
        reminder_scheduler: ReminderScheduler,
    ):
        """Initialize with required services."""
        self.token_storage = token_storage
        self.reminder_storage = reminder_storage
        self.reminder_scheduler = reminder_scheduler
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

        settings = get_settings()
        timezone = settings.default_timezone

        # Check Google auth
        credentials = await self.auth_service.get_credentials(user_id)
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": "User is not authorized in Google. Ask user to run /auth command.",
            }

        try:
            # Create title from summary or template
            event_summary = summary or template[:50] + ("..." if len(template) > 50 else "")
            
            # Build description with tag and prompt
            event_description = f"{REMINDER_TAG} {template}"
            
            # Build recurrence rule
            if schedule_type == "daily":
                recurrence = ["RRULE:FREQ=DAILY"]
            else:
                # Convert weekday to RRULE format (MO, TU, WE, TH, FR, SA, SU)
                weekday_map = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
                day_code = weekday_map[weekday] if weekday is not None else "MO"
                recurrence = [f"RRULE:FREQ=WEEKLY;BYDAY={day_code}"]
            
            # Calculate start/end times for today/next occurrence
            tz = ZoneInfo(timezone)
            now = datetime.now(tz)
            start_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # If time already passed today, schedule from tomorrow
            if start_dt <= now:
                start_dt += timedelta(days=1)
            
            # For weekly, adjust to correct weekday
            if schedule_type == "weekly" and weekday is not None:
                days_ahead = weekday - start_dt.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                start_dt += timedelta(days=days_ahead)
            
            end_dt = start_dt + timedelta(minutes=15)
            
            start_time_str = start_dt.isoformat()
            end_time_str = end_dt.isoformat()
            
            # Create Google Calendar event
            event = await self.calendar_service.create_event(
                credentials=credentials,
                summary=f"⏰ {event_summary}",
                start_time=start_time_str,
                end_time=end_time_str,
                description=event_description,
                recurrence=recurrence,
                timezone=timezone,
            )
            
            calendar_event_id = event.get("id", "")
            
            # Save to Redis for scheduler access
            reminder_id = await self.reminder_storage.save_reminder(
                user_id=user_id,
                template=template,
                schedule_type=schedule_type,
                time=time,
                timezone=timezone,
                weekday=weekday,
                calendar_event_id=calendar_event_id,
            )
            
            # Schedule in APScheduler
            reminder = await self.reminder_storage.get_reminder(reminder_id)
            if reminder:
                await self.reminder_scheduler._schedule_reminder(reminder)

            weekdays = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
            
            if schedule_type == "daily":
                schedule_desc = f"ежедневно в {time}"
            else:
                day_name = weekdays[weekday] if weekday is not None else "?"
                schedule_desc = f"каждый {day_name} в {time}"

            return {
                "success": True,
                "reminder_id": reminder_id,
                "calendar_event_id": calendar_event_id,
                "message": (
                    f"Напоминание создано! Буду отправлять '{template}' {schedule_desc} "
                    f"(часовой пояс: {timezone}). Событие добавлено в Google Calendar."
                ),
            }

        except Exception as e:
            logger.error(f"Error creating reminder: {e}")
            return {
                "success": False,
                "error": "scheduler_error",
                "message": f"Error creating reminder: {str(e)}",
            }
