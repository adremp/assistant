"""Reminder scheduler service using APScheduler and Google Calendar."""

import logging
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler import AsyncScheduler
from apscheduler.datastores.memory import MemoryDataStore
from apscheduler.eventbrokers.redis import RedisEventBroker
from apscheduler.triggers.cron import CronTrigger

from app.storage.reminders import ReminderStorage
from app.storage.tokens import TokenStorage
from app.constants import REMINDERS_CALENDAR_NAME
from app.utils.timezone import to_tzinfo

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """Scheduler for managing user reminders from Google Calendar."""

    def __init__(
        self,
        redis_url: str,
        bot: Bot,
        reminder_storage: ReminderStorage,
        token_storage: TokenStorage,
        llm_client: Any,  # LLMClient for processing prompts
    ):
        """
        Initialize reminder scheduler.

        Args:
            redis_url: Redis connection URL for event broker
            bot: Telegram bot instance
            reminder_storage: Storage for reminder data
            token_storage: Token storage for Google auth
            llm_client: LLM client for processing prompts
        """
        self.redis_url = redis_url
        self.bot = bot
        self.reminder_storage = reminder_storage
        self.token_storage = token_storage
        self.llm_client = llm_client
        self.scheduler: AsyncScheduler | None = None
        self._running = False

    async def start(self) -> None:
        """Start scheduler and restore reminders from Redis."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        # Create APScheduler with Redis event broker
        event_broker = RedisEventBroker(client_or_url=self.redis_url)
        data_store = MemoryDataStore()

        self.scheduler = AsyncScheduler(data_store, event_broker)
        
        # Start scheduler in background
        await self.scheduler.__aenter__()
        await self.scheduler.start_in_background()
        self._running = True

        # Restore existing reminders
        await self._restore_reminders()
        
        # Schedule daily sync at midnight
        await self.scheduler.add_schedule(
            self._sync_from_calendar,
            CronTrigger(hour=0, minute=0, timezone=ZoneInfo("UTC")),
            id="calendar_sync",
        )
        logger.info("Scheduled daily Calendar sync at 00:00 UTC")

        logger.info("Reminder scheduler started")

    async def stop(self) -> None:
        """Stop scheduler gracefully."""
        if not self._running or not self.scheduler:
            return

        await self.scheduler.__aexit__(None, None, None)
        self._running = False
        logger.info("Reminder scheduler stopped")

    async def _restore_reminders(self) -> None:
        """Restore all active reminders from storage."""
        if not self.scheduler:
            return

        reminders = await self.reminder_storage.get_all_active_reminders()
        for reminder in reminders:
            try:
                await self._schedule_reminder(reminder)
                logger.debug(f"Restored reminder {reminder['id']}")
            except Exception as e:
                logger.error(f"Failed to restore reminder {reminder['id']}: {e}")

        logger.info(f"Restored {len(reminders)} reminders")

    async def _schedule_reminder(self, reminder: dict[str, Any]) -> None:
        """Schedule a reminder in APScheduler."""
        if not self.scheduler:
            raise RuntimeError("Scheduler not started")

        reminder_id = reminder["id"]
        schedule_type = reminder["schedule_type"]
        time_str = reminder["time"]
        timezone = reminder.get("timezone")
        weekdays = reminder.get("weekdays")

        if not timezone:
            logger.error(f"Reminder {reminder_id} missing timezone, skipping")
            return

        hour, minute = map(int, time_str.split(":"))
        tzinfo = to_tzinfo(timezone)
        if tzinfo is None:
            logger.error(f"Invalid timezone '{timezone}' for reminder {reminder_id}")
            return

        # Create cron triggers
        if schedule_type == "daily":
            trigger = CronTrigger(hour=hour, minute=minute, timezone=tzinfo)
            await self.scheduler.add_schedule(
                self._send_reminder,
                trigger,
                id=f"reminder_{reminder_id}",
                args=[reminder_id],
            )
        elif schedule_type == "weekly" and weekdays:
            # For weekly, create one schedule per weekday
            for day in weekdays:
                trigger = CronTrigger(
                    day_of_week=day,
                    hour=hour,
                    minute=minute,
                    timezone=tzinfo,
                )
                await self.scheduler.add_schedule(
                    self._send_reminder,
                    trigger,
                    id=f"reminder_{reminder_id}_day{day}",
                    args=[reminder_id],
                )

        logger.info(f"Scheduled reminder {reminder_id}: {schedule_type} at {time_str}")

    async def _send_reminder(self, reminder_id: str) -> None:
        """Send reminder to user - call LLM with prompt and send response."""
        reminder = await self.reminder_storage.get_reminder(reminder_id)
        if not reminder:
            logger.warning(f"Reminder {reminder_id} not found, skipping")
            return

        if not reminder.get("is_active", True):
            logger.debug(f"Reminder {reminder_id} is inactive, skipping")
            return

        user_id = reminder["user_id"]
        prompt = reminder.get("prompt", "Напоминание")

        try:
            # Call LLM with prompt
            logger.info(f"Processing reminder {reminder_id} for user {user_id}")
            
            # Use LLM to generate response based on prompt
            response = await self.llm_client.process_message(
                user_id=user_id,
                message=prompt,
            )

            # Send LLM response to user
            await self.bot.send_message(
                chat_id=user_id,
                text=f"⏰ {response}",
            )

            logger.info(f"Sent reminder {reminder_id} to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send reminder {reminder_id}: {e}")

    async def add_reminder(
        self,
        user_id: int,
        prompt: str,
        schedule_type: str,
        time: str,
        timezone: str,
        weekdays: list[int] | None = None,
        event_id: str | None = None,
    ) -> str:
        """
        Schedule a new reminder.

        Args:
            user_id: Telegram user ID
            prompt: LLM prompt for reminder
            schedule_type: "daily" or "weekly"
            time: Time in HH:MM format
            timezone: User's timezone
            weekdays: List of weekdays (0-6) for weekly reminders
            event_id: Google Calendar event ID (optional)

        Returns:
            Reminder ID
        """
        if not self.scheduler:
            raise RuntimeError("Scheduler not started")

        if schedule_type not in ("daily", "weekly"):
            raise ValueError(f"Invalid schedule type: {schedule_type}")

        if schedule_type == "weekly" and not weekdays:
            raise ValueError("weekdays required for weekly reminders")

        # Save to storage
        reminder_id = await self.reminder_storage.save_reminder(
            user_id=user_id,
            prompt=prompt,
            schedule_type=schedule_type,
            time=time,
            timezone=timezone,
            weekdays=weekdays,
            event_id=event_id,
        )

        # Schedule it
        reminder = await self.reminder_storage.get_reminder(reminder_id)
        if reminder:
            await self._schedule_reminder(reminder)

        return reminder_id

    async def remove_reminder(self, reminder_id: str) -> bool:
        """Remove a scheduled reminder."""
        if not self.scheduler:
            raise RuntimeError("Scheduler not started")

        # Get reminder to find weekdays
        reminder = await self.reminder_storage.get_reminder(reminder_id)
        
        # Remove from APScheduler
        try:
            await self.scheduler.remove_schedule(f"reminder_{reminder_id}")
        except Exception:
            pass

        # Also remove weekday-specific schedules
        if reminder and reminder.get("weekdays"):
            for day in reminder["weekdays"]:
                try:
                    await self.scheduler.remove_schedule(f"reminder_{reminder_id}_day{day}")
                except Exception:
                    pass

        return await self.reminder_storage.delete_reminder(reminder_id)

    async def get_user_reminders(self, user_id: int) -> list[dict[str, Any]]:
        """Get all reminders for a user."""
        return await self.reminder_storage.get_reminders(user_id)

    async def _sync_from_calendar(self) -> None:
        """
        Sync reminders from Google Calendar 'Напоминания'.
        Reads recurring events, parses schedule from RRULE, and prompt from description.
        """
        from app.google.calendar import CalendarService
        from app.google.auth import GoogleAuthService
        from app.config import get_settings

        logger.info("Starting daily Calendar sync for reminders...")

        # Get existing reminders to find user IDs
        existing_reminders = await self.reminder_storage.get_all_active_reminders()
        user_ids = set(r.get("user_id") for r in existing_reminders if r.get("user_id"))

        # Delete all existing reminders and unschedule jobs
        for reminder in existing_reminders:
            reminder_id = reminder.get("id")
            if reminder_id and self.scheduler:
                try:
                    await self.scheduler.remove_schedule(f"reminder_{reminder_id}")
                except Exception:
                    pass
                for day in range(7):
                    try:
                        await self.scheduler.remove_schedule(f"reminder_{reminder_id}_day{day}")
                    except Exception:
                        pass

        await self.reminder_storage.delete_all_reminders()
        logger.info("Cleared all existing reminders before sync")

        settings = get_settings()
        calendar_service = CalendarService()
        auth_service = GoogleAuthService(settings, self.token_storage)

        synced_count = 0
        for user_id in user_ids:
            try:
                credentials = await auth_service.get_credentials(user_id)
                if not credentials:
                    continue

                # Get user timezone
                timezone = await self.token_storage.get_user_timezone(user_id, default="UTC")

                # Get reminders from dedicated Calendar
                reminders = await calendar_service.get_reminders(
                    credentials, 
                    calendar_name=REMINDERS_CALENDAR_NAME,
                )

                for rem in reminders:
                    reminder_id = await self.add_reminder(
                        user_id=user_id,
                        prompt=rem["prompt"],
                        schedule_type=rem["schedule_type"],
                        time=rem["time"],
                        timezone=timezone,
                        weekdays=rem.get("weekdays"),
                        event_id=rem["id"],
                    )
                    synced_count += 1
                    logger.info(f"Synced reminder from Calendar: {rem['id']} -> {reminder_id}")

            except Exception as e:
                logger.error(f"Error syncing Calendar for user {user_id}: {e}")

        logger.info(f"Calendar sync complete. Synced {synced_count} reminders.")
