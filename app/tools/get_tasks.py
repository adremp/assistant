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
        "Получить список задач из Google Tasks пользователя. "
        "Используй этот инструмент когда пользователь спрашивает о своих задачах, "
        "делах или todo-списке."
    )
    parameters = {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Максимальное количество задач (по умолчанию 20)",
                "default": 20,
            },
            "show_completed": {
                "type": "boolean",
                "description": "Показывать выполненные задачи (по умолчанию false)",
                "default": False,
            },
            "tasklist_id": {
                "type": "string",
                "description": "ID списка задач (по умолчанию основной список)",
                "default": "@default",
            },
        },
        "required": [],
    }

    def __init__(self, token_storage: TokenStorage):
        """
        Initialize tool with dependencies.

        Args:
            token_storage: Redis-based token storage
        """
        self.token_storage = token_storage
        self.tasks_service = TasksService()
        self.auth_service = GoogleAuthService(get_settings(), token_storage)

    async def execute(
        self,
        user_id: int,
        max_results: int = 20,
        show_completed: bool = False,
        tasklist_id: str = "@default",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute the tool to get tasks.

        Args:
            user_id: Telegram user ID
            max_results: Maximum number of tasks
            show_completed: Whether to show completed tasks
            tasklist_id: Task list ID

        Returns:
            Dictionary with tasks list or error message
        """
        # Check if user is authorized
        credentials = await self.auth_service.get_credentials(user_id)
        if credentials is None:
            return {
                "success": False,
                "error": "not_authorized",
                "message": (
                    "Пользователь не авторизован в Google. "
                    "Попроси пользователя выполнить команду /auth для авторизации."
                ),
            }

        try:
            tasks = await self.tasks_service.list_tasks(
                credentials=credentials,
                tasklist_id=tasklist_id,
                max_results=max_results,
                show_completed=show_completed,
            )

            if not tasks:
                return {
                    "success": True,
                    "tasks": [],
                    "message": "Список задач пуст.",
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
                "message": f"Ошибка при получении задач: {str(e)}",
            }
