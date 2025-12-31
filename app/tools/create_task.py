"""Tool: Create task in Google Tasks."""

import logging
from typing import Any

from app.tools.base import BaseTool
from app.google.tasks import TasksService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.config import get_settings

logger = logging.getLogger(__name__)


class CreateTaskTool(BaseTool):
    """Tool to create a new task in Google Tasks."""

    name = "create_task"
    description = (
        "Create a new task in user's Google Tasks. "
        "Use this tool when user wants to add a new task or todo item."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Task title",
            },
            "notes": {
                "type": "string",
                "description": "Task notes or description (optional)",
            },
            "due": {
                "type": "string",
                "description": (
                    "Due date in RFC 3339 format "
                    "(e.g., 2024-01-15T00:00:00.000Z)"
                ),
            },
        },
        "required": ["title"],
    }

    def __init__(self, token_storage: TokenStorage):
        self.token_storage = token_storage
        self.tasks_service = TasksService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        title: str,
        notes: str | None = None,
        due: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        logger.info(f"create_task called for user_id={user_id}, title={title}")
        
        credentials = await self.auth_service.get_credentials(user_id)
        
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": "User is not authorized in Google. Ask user to run /auth command.",
            }

        try:
            task = await self.tasks_service.create_task(
                credentials=credentials,
                title=title,
                notes=notes,
                due=due,
            )

            return {
                "success": True,
                "task": task,
                "message": f"Task '{title}' created successfully.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Error creating task: {str(e)}",
            }
