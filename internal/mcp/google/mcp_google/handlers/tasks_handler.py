"""MCP tools for Google Tasks."""

from mcp.server.fastmcp import FastMCP

from mcp_google.container import get_auth_repo, get_tasks_service
from mcp_google.handlers import _err, _not_authorized, _ok


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def get_tasks(
        user_id: int, max_results: int = 20, show_completed: bool = False
    ) -> str:
        """Get tasks from user's Google Tasks."""
        auth = await get_auth_repo()
        creds = await auth.get_credentials(user_id)
        if creds is None:
            return _not_authorized()
        try:
            svc = await get_tasks_service()
            tasks = await svc.list_tasks(
                credentials=creds,
                max_results=max_results,
                show_completed=show_completed,
            )
            return _ok({"tasks": tasks, "count": len(tasks)})
        except Exception as e:
            return _err(f"Error getting tasks: {e}")

    @mcp.tool()
    async def create_task(
        user_id: int, title: str, notes: str | None = None, due: str | None = None
    ) -> str:
        """Create a new task in user's Google Tasks."""
        auth = await get_auth_repo()
        creds = await auth.get_credentials(user_id)
        if creds is None:
            return _not_authorized()
        try:
            svc = await get_tasks_service()
            task = await svc.create_task(
                credentials=creds, title=title, notes=notes, due=due
            )
            return _ok(
                {"task": task, "message": f"Task '{title}' created successfully."}
            )
        except Exception as e:
            return _err(f"Error creating task: {e}")

    @mcp.tool()
    async def update_task(
        user_id: int,
        task_id: str,
        title: str | None = None,
        notes: str | None = None,
        due: str | None = None,
    ) -> str:
        """Update an existing task in Google Tasks."""
        auth = await get_auth_repo()
        creds = await auth.get_credentials(user_id)
        if creds is None:
            return _not_authorized()
        try:
            svc = await get_tasks_service()
            task = await svc.update_task(
                credentials=creds, task_id=task_id, title=title, notes=notes, due=due
            )
            return _ok(
                {"task": task, "message": f"Task '{task.get('title')}' updated."}
            )
        except Exception as e:
            return _err(f"Error updating task: {e}")

    @mcp.tool()
    async def complete_task(user_id: int, task_id: str) -> str:
        """Mark a task as completed in Google Tasks."""
        auth = await get_auth_repo()
        creds = await auth.get_credentials(user_id)
        if creds is None:
            return _not_authorized()
        try:
            svc = await get_tasks_service()
            task = await svc.complete_task(credentials=creds, task_id=task_id)
            return _ok(
                {
                    "task": task,
                    "message": f"Task '{task.get('title', task_id)}' marked as completed.",
                }
            )
        except Exception as e:
            return _err(f"Error completing task: {e}")
