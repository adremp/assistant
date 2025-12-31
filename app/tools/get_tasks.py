"""Tool: Get tasks from Google Tasks."""

from typing import Any

from app.tools.base import BaseTool
from app.google.tasks import TasksService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.config import get_settings


class GetTasksTool(BaseTool):
    """Tool to get tasks from Google Tasks."""

    name = "get_tasks"
    description = (
        "Get tasks from user's Google Tasks. "
        "Use this tool when user asks about their tasks, todos or task list."
    )
    parameters = {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Maximum number of tasks (default 20)",
                "default": 20,
            },
            "show_completed": {
                "type": "boolean",
                "description": "Show completed tasks (default false)",
                "default": False,
            },
        },
        "required": [],
    }

    def __init__(self, token_storage: TokenStorage):
        self.token_storage = token_storage
        self.tasks_service = TasksService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        max_results: int = 20,
        show_completed: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        credentials = await self.auth_service.get_credentials(user_id)
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": "User is not authorized in Google. Ask user to run /auth command.",
            }

        try:
            tasks = await self.tasks_service.list_tasks(
                credentials=credentials,
                max_results=max_results,
                show_completed=show_completed,
            )

            if not tasks:
                return {
                    "success": True,
                    "tasks": [],
                    "message": "No tasks in the list.",
                }

            return {
                "success": True,
                "tasks": tasks,
                "count": len(tasks),
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Error getting tasks: {str(e)}",
            }
