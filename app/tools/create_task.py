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
        "Создать новую задачу в Google Tasks пользователя. "
        "Используй этот инструмент когда пользователь хочет добавить новую задачу, "
        "дело в свой список или todo."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Название задачи",
            },
            "notes": {
                "type": "string",
                "description": "Заметки или описание задачи (опционально)",
            },
            "due": {
                "type": "string",
                "description": (
                    "Срок выполнения в формате RFC 3339 "
                    "(например: 2024-01-15T00:00:00.000Z)"
                ),
            },
            "tasklist_id": {
                "type": "string",
                "description": "ID списка задач (по умолчанию основной список)",
                "default": "@default",
            },
        },
        "required": ["title"],
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
        title: str,
        notes: str | None = None,
        due: str | None = None,
        tasklist_id: str = "@default",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute the tool to create a task.

        Args:
            user_id: Telegram user ID
            title: Task title
            notes: Task notes
            due: Due date in RFC 3339 format
            tasklist_id: Task list ID

        Returns:
            Dictionary with created task or error message
        """
        logger.info(f"create_task called for user_id={user_id}, title={title}")
        
        # Check if user is authorized
        credentials = await self.auth_service.get_credentials(user_id)
        logger.info(f"create_task credentials for user {user_id}: {credentials is not None}")
        
        if credentials is None:
            logger.warning(f"create_task: No credentials for user {user_id}")
            return {
                "success": False,
                "error": "not_authorized",
                "message": (
                    "Пользователь не авторизован в Google. "
                    "Попроси пользователя выполнить команду /auth для авторизации."
                ),
            }

        try:
            task = await self.tasks_service.create_task(
                credentials=credentials,
                title=title,
                notes=notes,
                due=due,
                tasklist_id=tasklist_id,
            )

            return {
                "success": True,
                "task": task,
                "message": f"Задача '{title}' успешно создана.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Ошибка при создании задачи: {str(e)}",
            }
