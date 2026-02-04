"""MCP Google Calendar & Tasks server."""

import json
import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pkg.token_storage import TokenStorage
from redis.asyncio import Redis

from mcp_google.config import get_settings
from mcp_google.google.auth import GoogleAuthReader
from mcp_google.google.calendar import CalendarService
from mcp_google.google.tasks import TasksService

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Configure security settings to allow Docker hostnames
security_settings = TransportSecuritySettings(
    allowed_hosts=["mcp-google:8000", "localhost:8000", "127.0.0.1:8000", "*"]
)
mcp = FastMCP("google-services", transport_security=security_settings)
settings = get_settings()

_redis: Redis | None = None
_token_storage: TokenStorage | None = None
_auth_reader: GoogleAuthReader | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url)
    return _redis


async def get_auth_reader() -> GoogleAuthReader:
    global _token_storage, _auth_reader
    if _auth_reader is None:
        redis = await get_redis()
        _token_storage = TokenStorage(redis, settings.token_ttl_seconds)
        _auth_reader = GoogleAuthReader(
            _token_storage, settings.google_credentials_path
        )
    return _auth_reader


async def get_credentials(user_id: int):
    auth = await get_auth_reader()
    return await auth.get_credentials(user_id)


def _not_authorized() -> str:
    return json.dumps(
        {
            "success": False,
            "error": "not_authorized",
            "message": "User is not authorized in Google. Ask user to run /auth command.",
        },
        ensure_ascii=False,
    )


def _error(msg: str) -> str:
    return json.dumps(
        {"success": False, "error": "api_error", "message": msg}, ensure_ascii=False
    )


def _ok(data: dict) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False)


@mcp.tool()
async def get_calendar_events(
    user_id: int, max_results: int = 10, time_min: str | None = None
) -> str:
    """Get upcoming events from user's Google Calendar."""
    creds = await get_credentials(user_id)
    if creds is None:
        return _not_authorized()
    try:
        service = CalendarService()
        events = await service.list_events(
            credentials=creds, max_results=max_results, time_min=time_min
        )
        return _ok({"events": events, "count": len(events)})
    except Exception as e:
        return _error(f"Error getting events: {e}")


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
    creds = await get_credentials(user_id)
    if creds is None:
        return _not_authorized()
    try:
        service = CalendarService()
        tz = await service.get_user_timezone(creds)
        # Save timezone
        auth = await get_auth_reader()
        await auth.token_storage.set_user_timezone(user_id, tz)

        recurrence = None
        if freq and freq != "once":
            freq_upper = freq.upper()
            if freq == "weekly" and freq_days:
                days_str = ",".join(freq_days)
                recurrence = [f"RRULE:FREQ={freq_upper};BYDAY={days_str}"]
            else:
                recurrence = [f"RRULE:FREQ={freq_upper}"]

        event = await service.create_event(
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
        return _error(f"Error creating event: {e}")


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
    creds = await get_credentials(user_id)
    if creds is None:
        return _not_authorized()
    try:
        service = CalendarService()
        event = await service.update_event(
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
        return _error(f"Error updating event: {e}")


@mcp.tool()
async def get_tasks(
    user_id: int, max_results: int = 20, show_completed: bool = False
) -> str:
    """Get tasks from user's Google Tasks."""
    creds = await get_credentials(user_id)
    if creds is None:
        return _not_authorized()
    try:
        service = TasksService()
        tasks = await service.list_tasks(
            credentials=creds, max_results=max_results, show_completed=show_completed
        )
        return _ok({"tasks": tasks, "count": len(tasks)})
    except Exception as e:
        return _error(f"Error getting tasks: {e}")


@mcp.tool()
async def create_task(
    user_id: int, title: str, notes: str | None = None, due: str | None = None
) -> str:
    """Create a new task in user's Google Tasks."""
    creds = await get_credentials(user_id)
    if creds is None:
        return _not_authorized()
    try:
        service = TasksService()
        task = await service.create_task(
            credentials=creds, title=title, notes=notes, due=due
        )
        return _ok({"task": task, "message": f"Task '{title}' created successfully."})
    except Exception as e:
        return _error(f"Error creating task: {e}")


@mcp.tool()
async def update_task(
    user_id: int,
    task_id: str,
    title: str | None = None,
    notes: str | None = None,
    due: str | None = None,
) -> str:
    """Update an existing task in Google Tasks."""
    creds = await get_credentials(user_id)
    if creds is None:
        return _not_authorized()
    try:
        service = TasksService()
        task = await service.update_task(
            credentials=creds, task_id=task_id, title=title, notes=notes, due=due
        )
        return _ok({"task": task, "message": f"Task '{task.get('title')}' updated."})
    except Exception as e:
        return _error(f"Error updating task: {e}")


@mcp.tool()
async def complete_task(user_id: int, task_id: str) -> str:
    """Mark a task as completed in Google Tasks."""
    creds = await get_credentials(user_id)
    if creds is None:
        return _not_authorized()
    try:
        service = TasksService()
        task = await service.complete_task(credentials=creds, task_id=task_id)
        return _ok(
            {
                "task": task,
                "message": f"Task '{task.get('title', task_id)}' marked as completed.",
            }
        )
    except Exception as e:
        return _error(f"Error completing task: {e}")


if __name__ == "__main__":
    import uvicorn

    # Get the HTTP ASGI app and run with uvicorn to bind to 0.0.0.0
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
