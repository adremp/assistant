"""Tool: Update task in Google Tasks."""

import logging
from typing import Any

from app.tools.base import BaseTool
from app.google.tasks import TasksService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.config import get_settings

logger = logging.getLogger(__name__)


class UpdateTaskTool(BaseTool):
    """Tool to update an existing task in Google Tasks."""

    name = "update_task"
    description = (
        "Update an existing task in Google Tasks. "
        "Use this tool to change task title, description or due date."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "ID of the task to update",
            },
            "title": {
                "type": "string",
                "description": "New task title (optional)",
            },
            "notes": {
                "type": "string",
                "description": "New task description (optional)",
            },
            "due": {
                "type": "string",
                "description": "New due date in RFC 3339 format (optional)",
            },
        },
        "required": ["task_id"],
    }

    def __init__(self, token_storage: TokenStorage):
        self.token_storage = token_storage
        self.tasks_service = TasksService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        task_id: str,
        title: str | None = None,
        notes: str | None = None,
        due: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        credentials = await self.auth_service.get_credentials(user_id)
        
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": "User is not authorized. Ask user to run /auth command.",
            }

        try:
            task = await self.tasks_service.update_task(
                credentials=credentials,
                task_id=task_id,
                title=title,
                notes=notes,
                due=due,
            )

            return {
                "success": True,
                "task": task,
                "message": f"Task '{task.get('title')}' updated.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Error updating task: {str(e)}",
            }
