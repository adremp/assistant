"""Google Calendar API client."""

import logging
from datetime import datetime, timezone
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class CalendarService:
    """Client for Google Calendar API."""

    def __init__(self):
        """Initialize calendar service."""
        pass

    def _get_service(self, credentials: Credentials):
        """
        Build Calendar API service.

        Args:
            credentials: Valid Google credentials

        Returns:
            Calendar API service
        """
        return build("calendar", "v3", credentials=credentials)

    async def get_user_timezone(self, credentials: Credentials) -> str:
        """
        Get user's timezone from Google Calendar settings.

        Args:
            credentials: Valid Google credentials

        Returns:
            User's timezone string (e.g., "Asia/Almaty")
        """
        service = self._get_service(credentials)

        try:
            setting = service.settings().get(setting="timezone").execute()
            timezone_value = setting.get("value", "UTC")
            logger.debug(f"Got user timezone: {timezone_value}")
            return timezone_value
        except HttpError as e:
            logger.error(f"Failed to get timezone: {e}")
            return "UTC"

    async def list_events(
        self,
        credentials: Credentials,
        max_results: int = 10,
        time_min: str | None = None,
        calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        """
        List upcoming events from calendar.

        Args:
            credentials: Valid Google credentials
            max_results: Maximum number of events to return
            time_min: Start time in ISO format (default: now)
            calendar_id: Calendar ID (default: primary)

        Returns:
            List of event dictionaries
        """
        service = self._get_service(credentials)

        if time_min is None:
            time_min = datetime.now(timezone.utc).isoformat()

        try:
            events_result = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])
            logger.debug(f"Retrieved {len(events)} events")

            return [
                {
                    "id": event.get("id"),
                    "summary": event.get("summary", "Без названия"),
                    "start": event.get("start", {}).get("dateTime")
                    or event.get("start", {}).get("date"),
                    "end": event.get("end", {}).get("dateTime")
                    or event.get("end", {}).get("date"),
                    "description": event.get("description"),
                    "location": event.get("location"),
                    "recurrence": event.get("recurrence"),
                    "recurring_event_id": event.get("recurringEventId"),
                    "html_link": event.get("htmlLink"),
                }
                for event in events
            ]

        except HttpError as e:
            logger.error(f"Calendar API error: {e}")
            raise

    async def create_event(
        self,
        credentials: Credentials,
        summary: str,
        start_time: str,
        end_time: str,
        description: str | None = None,
        location: str | None = None,
        recurrence: list[str] | None = None,
        timezone: str | None = None,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """
        Create a new calendar event.

        Args:
            credentials: Valid Google credentials
            summary: Event title
            start_time: Start time in ISO format
            end_time: End time in ISO format
            description: Event description
            location: Event location
            recurrence: List of RRULE strings (e.g., ["RRULE:FREQ=DAILY"])
            timezone: Timezone for recurring events (e.g., "Asia/Almaty")
            calendar_id: Calendar ID (default: primary)

        Returns:
            Created event dictionary
        """
        service = self._get_service(credentials)

        # Build start/end with timezone if provided
        if timezone:
            event_body = {
                "summary": summary,
                "start": {"dateTime": start_time, "timeZone": timezone},
                "end": {"dateTime": end_time, "timeZone": timezone},
            }
        else:
            event_body = {
                "summary": summary,
                "start": {"dateTime": start_time},
                "end": {"dateTime": end_time},
            }

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if recurrence:
            event_body["recurrence"] = recurrence

        try:
            event = (
                service.events()
                .insert(calendarId=calendar_id, body=event_body)
                .execute()
            )
            logger.info(f"Created event: {event.get('id')}")

            return {
                "id": event.get("id"),
                "summary": event.get("summary"),
                "start": event.get("start", {}).get("dateTime"),
                "end": event.get("end", {}).get("dateTime"),
                "description": event.get("description"),
                "recurrence": event.get("recurrence"),
                "html_link": event.get("htmlLink"),
            }

        except HttpError as e:
            logger.error(f"Failed to create event: {e}")
            raise

    async def update_event(
        self,
        credentials: Credentials,
        event_id: str,
        summary: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        description: str | None = None,
        location: str | None = None,
        recurrence: list[str] | None = None,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """
        Update an existing calendar event.

        Args:
            credentials: Valid Google credentials
            event_id: Event ID to update
            summary: New event title
            start_time: New start time in ISO format
            end_time: New end time in ISO format
            description: New event description
            location: New event location
            recurrence: List of RRULE strings (e.g., ["RRULE:FREQ=DAILY"])
            calendar_id: Calendar ID (default: primary)

        Returns:
            Updated event dictionary
        """
        service = self._get_service(credentials)

        try:
            # Get existing event
            event = (
                service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )

            # Update fields
            if summary:
                event["summary"] = summary
            if start_time:
                event["start"] = {"dateTime": start_time}
            if end_time:
                event["end"] = {"dateTime": end_time}
            if description is not None:
                event["description"] = description
            if location is not None:
                event["location"] = location
            if recurrence is not None:
                event["recurrence"] = recurrence

            updated = (
                service.events()
                .update(calendarId=calendar_id, eventId=event_id, body=event)
                .execute()
            )
            logger.info(f"Updated event: {event_id}")

            return {
                "id": updated.get("id"),
                "summary": updated.get("summary"),
                "start": updated.get("start", {}).get("dateTime"),
                "end": updated.get("end", {}).get("dateTime"),
                "description": updated.get("description"),
                "recurrence": updated.get("recurrence"),
                "html_link": updated.get("htmlLink"),
            }

        except HttpError as e:
            logger.error(f"Failed to update event {event_id}: {e}")
            raise

    async def delete_event(
        self,
        credentials: Credentials,
        event_id: str,
        calendar_id: str = "primary",
    ) -> bool:
        """
        Delete a calendar event.

        Args:
            credentials: Valid Google credentials
            event_id: Event ID to delete
            calendar_id: Calendar ID (default: primary)

        Returns:
            True if deleted successfully
        """
        service = self._get_service(credentials)

        try:
            service.events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()
            logger.info(f"Deleted event: {event_id}")
            return True

        except HttpError as e:
            logger.error(f"Failed to delete event {event_id}: {e}")
            raise
