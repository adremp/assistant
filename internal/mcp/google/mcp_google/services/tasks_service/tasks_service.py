"""Google Tasks API client."""

import logging
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class TasksService:
    """Client for Google Tasks API."""

    def _get_service(self, credentials: Credentials):
        return build("tasks", "v1", credentials=credentials)

    async def list_tasklists(
        self,
        credentials: Credentials,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        service = self._get_service(credentials)
        try:
            result = service.tasklists().list(maxResults=max_results).execute()
            tasklists = result.get("items", [])
            return [{"id": tl.get("id"), "title": tl.get("title")} for tl in tasklists]
        except HttpError as e:
            logger.error(f"Tasks API error: {e}")
            raise

    async def list_tasks(
        self,
        credentials: Credentials,
        tasklist_id: str = "@default",
        max_results: int = 20,
        show_completed: bool = False,
    ) -> list[dict[str, Any]]:
        service = self._get_service(credentials)
        try:
            result = (
                service.tasks()
                .list(
                    tasklist=tasklist_id,
                    maxResults=max_results,
                    showCompleted=show_completed,
                )
                .execute()
            )
            tasks = result.get("items", [])
            return [
                {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "notes": task.get("notes"),
                    "due": task.get("due"),
                    "status": task.get("status"),
                    "completed": task.get("completed"),
                }
                for task in tasks
            ]
        except HttpError as e:
            logger.error(f"Tasks API error: {e}")
            raise

    async def create_task(
        self,
        credentials: Credentials,
        title: str,
        notes: str | None = None,
        due: str | None = None,
        tasklist_id: str = "@default",
    ) -> dict[str, Any]:
        service = self._get_service(credentials)
        task_body: dict[str, Any] = {"title": title}
        if notes:
            task_body["notes"] = notes
        if due:
            task_body["due"] = due
        try:
            task = (
                service.tasks().insert(tasklist=tasklist_id, body=task_body).execute()
            )
            return {
                "id": task.get("id"),
                "title": task.get("title"),
                "notes": task.get("notes"),
                "due": task.get("due"),
                "status": task.get("status"),
            }
        except HttpError as e:
            logger.error(f"Failed to create task: {e}")
            raise

    async def update_task(
        self,
        credentials: Credentials,
        task_id: str,
        title: str | None = None,
        notes: str | None = None,
        due: str | None = None,
        tasklist_id: str = "@default",
    ) -> dict[str, Any]:
        service = self._get_service(credentials)
        try:
            task = service.tasks().get(tasklist=tasklist_id, task=task_id).execute()
            if title:
                task["title"] = title
            if notes is not None:
                task["notes"] = notes
            if due is not None:
                task["due"] = due
            updated = (
                service.tasks()
                .update(tasklist=tasklist_id, task=task_id, body=task)
                .execute()
            )
            return {
                "id": updated.get("id"),
                "title": updated.get("title"),
                "notes": updated.get("notes"),
                "due": updated.get("due"),
                "status": updated.get("status"),
            }
        except HttpError as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            raise

    async def complete_task(
        self,
        credentials: Credentials,
        task_id: str,
        tasklist_id: str = "@default",
    ) -> dict[str, Any]:
        service = self._get_service(credentials)
        try:
            task = service.tasks().get(tasklist=tasklist_id, task=task_id).execute()
            task["status"] = "completed"
            updated = (
                service.tasks()
                .update(tasklist=tasklist_id, task=task_id, body=task)
                .execute()
            )
            return {
                "id": updated.get("id"),
                "title": updated.get("title"),
                "status": updated.get("status"),
                "completed": updated.get("completed"),
            }
        except HttpError as e:
            logger.error(f"Failed to complete task {task_id}: {e}")
            raise

    async def delete_task(
        self,
        credentials: Credentials,
        task_id: str,
        tasklist_id: str = "@default",
    ) -> bool:
        service = self._get_service(credentials)
        try:
            service.tasks().delete(tasklist=tasklist_id, task=task_id).execute()
            return True
        except HttpError as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            raise

    async def toggle_task_status(
        self,
        credentials: Credentials,
        task_id: str,
        tasklist_id: str = "@default",
    ) -> dict[str, Any]:
        service = self._get_service(credentials)
        try:
            task = service.tasks().get(tasklist=tasklist_id, task=task_id).execute()
            current_status = task.get("status", "needsAction")
            if current_status == "completed":
                task["status"] = "needsAction"
                task.pop("completed", None)
            else:
                task["status"] = "completed"
            updated = (
                service.tasks()
                .update(tasklist=tasklist_id, task=task_id, body=task)
                .execute()
            )
            return {
                "id": updated.get("id"),
                "title": updated.get("title"),
                "status": updated.get("status"),
            }
        except HttpError as e:
            logger.error(f"Failed to toggle task {task_id}: {e}")
            raise

    async def create_completed_task(
        self,
        credentials: Credentials,
        title: str,
        notes: str | None = None,
        tasklist_id: str = "@default",
    ) -> dict[str, Any]:
        service = self._get_service(credentials)
        task_body: dict[str, Any] = {
            "title": title,
            "status": "completed",
        }
        if notes:
            task_body["notes"] = notes
        try:
            task = (
                service.tasks().insert(tasklist=tasklist_id, body=task_body).execute()
            )
            return {
                "id": task.get("id"),
                "title": task.get("title"),
                "notes": task.get("notes"),
                "status": task.get("status"),
                "completed": task.get("completed"),
            }
        except HttpError as e:
            logger.error(f"Failed to create completed task: {e}")
            raise
