"""Tool: Complete task in Google Tasks."""

from typing import Any

from app.tools.base import BaseTool
from app.google.tasks import TasksService
from app.google.auth import GoogleAuthService
from app.storage.tokens import TokenStorage
from app.config import get_settings


class CompleteTaskTool(BaseTool):
    """Tool to mark a task as completed in Google Tasks."""

    name = "complete_task"
    description = (
        "Отметить задачу как выполненную в Google Tasks. "
        "Используй этот инструмент когда пользователь хочет завершить задачу, "
        "отметить её выполненной или закрыть."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "ID задачи для завершения",
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
        **kwargs: Any,
    ) -> dict[str, Any]:
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
            task = await self.tasks_service.complete_task(
                credentials=credentials,
                task_id=task_id,
            )

            return {
                "success": True,
                "task": task,
                "message": f"Задача '{task.get('title', task_id)}' отмечена как выполненная.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "api_error",
                "message": f"Ошибка при завершении задачи: {str(e)}",
            }
