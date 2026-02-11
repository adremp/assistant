"""MCP tools for Google Calendar."""

from mcp.server.fastmcp import FastMCP

from mcp_google.container import get_auth_repo, get_calendar_service
from mcp_google.handlers import _err, _not_authorized, _ok


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_calendar_events(
        user_id: int, max_results: int = 10, time_min: str | None = None
    ) -> str:
        """Get upcoming events from user's Google Calendar."""
        auth = await get_auth_repo()
        creds = await auth.get_credentials(user_id)
        if creds is None:
            return _not_authorized()
        try:
            cal = await get_calendar_service()
            events = await cal.list_events(
                credentials=creds, max_results=max_results, time_min=time_min
            )
            return _ok({"events": events, "count": len(events)})
        except Exception as e:
            return _err(f"Error getting events: {e}")

    @mcp.tool()
    async def create_calendar_event(
        user_id: int,
        summary: str,
        start_time: str,
        end_time: str,
        description: str | None = None,
        freq: str | None = None,
        freq_days: list[str] | None = None,
    ) -> str:
        """Create a new event in user's Google Calendar. freq: once/daily/weekly/monthly/yearly. freq_days: MO,TU,WE,TH,FR,SA,SU for weekly."""
        auth = await get_auth_repo()
        creds = await auth.get_credentials(user_id)
        if creds is None:
            return _not_authorized()
        try:
            cal = await get_calendar_service()
            tz = await cal.get_user_timezone(creds)
            # Save timezone
            await auth.token_storage.set_user_timezone(user_id, tz)

            recurrence = None
            if freq and freq != "once":
                freq_upper = freq.upper()
                if freq == "weekly" and freq_days:
                    days_str = ",".join(freq_days)
                    recurrence = [f"RRULE:FREQ={freq_upper};BYDAY={days_str}"]
                else:
                    recurrence = [f"RRULE:FREQ={freq_upper}"]

            event = await cal.create_event(
                credentials=creds,
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
                recurrence=recurrence,
                timezone=tz,
            )
            return _ok(
                {"event": event, "message": f"Event '{summary}' created successfully."}
            )
        except Exception as e:
            return _err(f"Error creating event: {e}")

    @mcp.tool()
    async def update_calendar_event(
        user_id: int,
        event_id: str,
        summary: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        description: str | None = None,
    ) -> str:
        """Update an existing event in Google Calendar."""
        auth = await get_auth_repo()
        creds = await auth.get_credentials(user_id)
        if creds is None:
            return _not_authorized()
        try:
            cal = await get_calendar_service()
            event = await cal.update_event(
                credentials=creds,
                event_id=event_id,
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
            )
            return _ok(
                {"event": event, "message": f"Event '{event.get('summary')}' updated."}
            )
        except Exception as e:
            return _err(f"Error updating event: {e}")
