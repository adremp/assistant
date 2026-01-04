"""Reminder scheduler service using APScheduler."""

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler import AsyncScheduler
from apscheduler.datastores.memory import MemoryDataStore
from apscheduler.eventbrokers.redis import RedisEventBroker
from apscheduler.triggers.cron import CronTrigger

from app.storage.reminders import ReminderStorage
from app.storage.pending_responses import PendingResponseStorage
from app.storage.tokens import TokenStorage
from app.constants import REMINDER_TAG
from app.utils.timezone import to_tzinfo

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """Scheduler for managing user reminders using APScheduler."""

    def __init__(
        self,
        redis_url: str,
        bot: Bot,
        reminder_storage: ReminderStorage,
        pending_storage: PendingResponseStorage,
        token_storage: TokenStorage,
    ):
        """
        Initialize reminder scheduler.

        Args:
            redis_url: Redis connection URL for event broker
            bot: Telegram bot instance
            reminder_storage: Storage for reminder data
            pending_storage: Storage for pending response tracking
            token_storage: Token storage for Google auth
        """
        self.redis_url = redis_url
        self.bot = bot
        self.reminder_storage = reminder_storage
        self.pending_storage = pending_storage
        self.token_storage = token_storage
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
        logger.info("Scheduled daily calendar sync at 00:00")

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
        weekday = reminder.get("weekday")

        if not timezone:
            logger.error(f"Reminder {reminder_id} missing timezone, skipping schedule")
            return

        # Parse time (HH:MM format)
        hour, minute = map(int, time_str.split(":"))

        tzinfo = to_tzinfo(timezone)
        if tzinfo is None:
            logger.error(f"Invalid timezone '{timezone}' for reminder {reminder_id}, skipping schedule")
            return

        # Create cron trigger
        if schedule_type == "daily":
            trigger = CronTrigger(
                hour=hour,
                minute=minute,
                timezone=tzinfo,
            )
        elif schedule_type == "weekly":
            # APScheduler uses 0=Monday, 6=Sunday (same as our format)
            trigger = CronTrigger(
                day_of_week=weekday,
                hour=hour,
                minute=minute,
                timezone=tzinfo,
            )
        else:
            raise ValueError(f"Unknown schedule type: {schedule_type}")

        # Schedule the job
        await self.scheduler.add_schedule(
            self._send_reminder,
            trigger,
            id=f"reminder_{reminder_id}",
            args=[reminder_id],
        )

        logger.info(f"Scheduled reminder {reminder_id}: {schedule_type} at {time_str} ({timezone})")

    async def _send_reminder(self, reminder_id: str) -> None:
        """Send reminder to user (called by scheduler)."""
        reminder = await self.reminder_storage.get_reminder(reminder_id)
        if not reminder:
            logger.warning(f"Reminder {reminder_id} not found, skipping")
            return

        if not reminder.get("is_active", True):
            logger.debug(f"Reminder {reminder_id} is inactive, skipping")
            return

        user_id = reminder["user_id"]
        template = reminder["template"]

        try:
            # Send template to user
            await self.bot.send_message(
                chat_id=user_id,
                text=f"⏰ Напоминание:\n\n{template}\n\n💬 Ответьте текстом или голосовым сообщением.",
            )

            # Set pending response state
            await self.pending_storage.set_pending(
                user_id=user_id,
                reminder_id=reminder_id,
                template=template,
            )

            logger.info(f"Sent reminder {reminder_id} to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send reminder {reminder_id} to user {user_id}: {e}")

    async def add_reminder(
        self,
        user_id: int,
        template: str,
        schedule_type: str,
        time: str,
        timezone: str | None = None,
        weekday: int | None = None,
    ) -> str:
        """
        Schedule a new reminder.

        Args:
            user_id: Telegram user ID
            template: Reminder message template
            schedule_type: "daily" or "weekly"
            time: Time in HH:MM format
            timezone: User's timezone
            weekday: Day of week (0-6) for weekly reminders

        Returns:
            Reminder ID
        """
        if not self.scheduler:
            raise RuntimeError("Scheduler not started")

        if timezone is None:
            raise ValueError("timezone is required for reminders")

        # Validate schedule type
        if schedule_type not in ("daily", "weekly"):
            raise ValueError(f"Invalid schedule type: {schedule_type}")

        if schedule_type == "weekly" and weekday is None:
            raise ValueError("weekday is required for weekly reminders")

        # Save to storage
        reminder_id = await self.reminder_storage.save_reminder(
            user_id=user_id,
            template=template,
            schedule_type=schedule_type,
            time=time,
            timezone=timezone,
            weekday=weekday,
        )

        # Get the saved reminder and schedule it
        reminder = await self.reminder_storage.get_reminder(reminder_id)
        if reminder:
            await self._schedule_reminder(reminder)

        return reminder_id

    async def remove_reminder(self, reminder_id: str) -> bool:
        """
        Remove a scheduled reminder.

        Args:
            reminder_id: Reminder ID

        Returns:
            True if removed, False if not found
        """
        if not self.scheduler:
            raise RuntimeError("Scheduler not started")

        # Remove from APScheduler
        try:
            await self.scheduler.remove_schedule(f"reminder_{reminder_id}")
        except Exception as e:
            logger.debug(f"Schedule not found in APScheduler: {e}")

        # Remove from storage
        return await self.reminder_storage.delete_reminder(reminder_id)

    async def get_user_reminders(self, user_id: int) -> list[dict[str, Any]]:
        """
        Get all reminders for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of reminder data dictionaries
        """
        return await self.reminder_storage.get_reminders(user_id)

    async def _sync_from_calendar(self) -> None:
        """
        Sync reminders from Google Calendar.
        Deletes all existing reminders, then recreates from Calendar events with #напоминание tag.
        """
        from app.google.calendar import CalendarService
        from app.google.auth import GoogleAuthService
        from app.config import get_settings
        
        logger.info("Starting daily calendar sync for reminders...")
        
        # Get users before deleting (need to know which users to sync)
        existing_reminders = await self.reminder_storage.get_all_active_reminders()
        user_ids = set(r.get("user_id") for r in existing_reminders if r.get("user_id"))
        
        # Delete all existing reminders and unschedule jobs
        for reminder in existing_reminders:
            reminder_id = reminder.get("id")
            if reminder_id and self.scheduler:
                try:
                    await self.scheduler.remove_schedule(f"reminder_{reminder_id}")
                except Exception:
                    pass  # Job might not exist
        
        await self.reminder_storage.delete_all_reminders()
        logger.info("Deleted all existing reminders before sync")
        
        settings = get_settings()
        calendar_service = CalendarService()
        auth_service = GoogleAuthService(settings, self.token_storage)
        
        synced_count = 0
        synced_event_ids: set[str] = set()  # Track to avoid duplicates
        for user_id in user_ids:
            try:
                credentials = await auth_service.get_credentials(user_id)
                if not credentials:
                    continue
                
                # Get upcoming events (including recurring instances)
                events = await calendar_service.list_events(
                    credentials=credentials,
                    max_results=50,
                )
                
                for event in events:
                    description = event.get("description", "") or ""
                    
                    # Check for reminder tag
                    if not description.startswith(REMINDER_TAG):
                        continue
                    
                    # Get event ID (use recurring parent if available)
                    recurring_event_id = event.get("recurring_event_id")
                    event_id = recurring_event_id or event.get("id")
                    
                    # Skip if already synced (recurring events can appear multiple times)
                    if event_id in synced_event_ids:
                        continue
                    
                    # Parse template from description
                    template = description[len(REMINDER_TAG):].strip()
                    if not template:
                        continue
                    
                    # Parse time from event
                    start_str = event.get("start", "")
                    if not start_str:
                        continue
                    
                    try:
                        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        time_str = start_dt.strftime("%H:%M")
                        tzinfo = start_dt.tzinfo
                        tz_offset = start_dt.utcoffset()
                        if tzinfo and getattr(tzinfo, "key", None):
                            timezone_value = tzinfo.key
                        elif tz_offset is not None:
                            total_minutes = int(tz_offset.total_seconds() // 60)
                            hours, minutes = divmod(abs(total_minutes), 60)
                            sign = "+" if total_minutes >= 0 else "-"
                            timezone_value = f"{sign}{hours:02d}:{minutes:02d}"
                        else:
                            logger.warning(f"Event {event_id} missing timezone, skipping")
                            continue
                    except (ValueError, AttributeError):
                        continue
                    
                    # Determine schedule type from recurrence
                    recurrence = event.get("recurrence", [])
                    schedule_type = "daily"  # Default
                    weekday = None
                    
                    for rule in recurrence:
                        if "FREQ=WEEKLY" in rule:
                            schedule_type = "weekly"
                            # Parse weekday from BYDAY
                            if "BYDAY=" in rule:
                                day_map = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
                                for day, idx in day_map.items():
                                    if day in rule:
                                        weekday = idx
                                        break
                            if weekday is None:
                                weekday = start_dt.weekday()
                            break
                    
                    # Create reminder in storage
                    reminder_id = await self.reminder_storage.save_reminder(
                        user_id=user_id,
                        template=template,
                        schedule_type=schedule_type,
                        time=time_str,
                        timezone=timezone_value,
                        weekday=weekday,
                        calendar_event_id=event_id,
                    )
                    
                    # Schedule reminder
                    reminder = await self.reminder_storage.get_reminder(reminder_id)
                    if reminder:
                        await self._schedule_reminder(reminder)
                        synced_count += 1
                        logger.info(f"Synced reminder from calendar: {event_id} -> {reminder_id}")
                    
                    synced_event_ids.add(event_id)
                    
            except Exception as e:
                logger.error(f"Error syncing calendar for user {user_id}: {e}")
        
        logger.info(f"Calendar sync complete. Synced {synced_count} new reminders.")
