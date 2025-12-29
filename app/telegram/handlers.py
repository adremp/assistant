"""Telegram message handlers."""

import logging
import re
from typing import Any

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.llm.client import LLMClient
from app.storage.tokens import TokenStorage

logger = logging.getLogger(__name__)

router = Router(name="main")


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Get main menu keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Задачи на сегодня", callback_data="tasks_today")],
        [InlineKeyboardButton(text="📅 События на сегодня", callback_data="events_today")],
    ])


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """
    Handle /start command.

    Args:
        message: Telegram message
    """
    user = message.from_user
    user_name = user.first_name if user else "друг"

    await message.answer(
        f"👋 Привет, {user_name}!\n\n"
        "Я — твой персональный ассистент для управления календарём и задачами.\n\n"
        "Команды:\n"
        "/auth — авторизация в Google\n"
        "/tasks — задачи на сегодня\n"
        "/clear — очистить историю диалога\n\n"
        "💬 Или просто напиши, что тебе нужно!",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """
    Handle /help command.

    Args:
        message: Telegram message
    """
    await message.answer(
        "📚 Справка\n\n"
        "Примеры запросов:\n"
        "- Покажи мои события на сегодня\n"
        "- Создай встречу завтра в 10:00\n"
        "- Какие у меня задачи?\n"
        "- Добавь задачу купить молоко\n\n"
        "Команды:\n"
        "/start — начать работу\n"
        "/auth — авторизация в Google\n"
        "/tasks — задачи на сегодня\n"
        "/clear — очистить историю диалога"
    )


@router.message(Command("tasks"))
async def handle_tasks_command(message: Message, token_storage: TokenStorage) -> None:
    """Handle /tasks command - show today's tasks."""
    user_id = message.from_user.id if message.from_user else 0
    await show_tasks_today(message, user_id, token_storage)


@router.callback_query(F.data == "tasks_today")
async def handle_tasks_today_callback(
    callback: CallbackQuery,
    token_storage: TokenStorage,
) -> None:
    """Handle tasks_today button click."""
    await callback.answer()
    user_id = callback.from_user.id
    await show_tasks_today(callback.message, user_id, token_storage)


@router.callback_query(F.data.startswith("toggle_task:"))
async def handle_toggle_task(
    callback: CallbackQuery,
    token_storage: TokenStorage,
) -> None:
    """Handle task completion toggle."""
    from app.google.auth import GoogleAuthService
    from app.google.tasks import TasksService
    from app.config import get_settings
    
    await callback.answer("Обновляю...")
    
    user_id = callback.from_user.id
    task_id = callback.data.split(":")[1]
    
    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)
    credentials = await auth_service.get_credentials(user_id)
    
    if not credentials:
        await callback.message.answer("Требуется авторизация. Выполните /auth")
        return
    
    try:
        tasks_service = TasksService()
        await tasks_service.toggle_task_status(credentials, task_id)
        # Refresh the task list
        await show_tasks_today(callback.message, user_id, token_storage, edit=True)
    except Exception as e:
        logger.error(f"Toggle task error: {e}")
        await callback.message.answer("Ошибка при обновлении задачи")


async def show_tasks_today(
    message: Message,
    user_id: int,
    token_storage: TokenStorage,
    edit: bool = False,
) -> None:
    """Show today's tasks with checkboxes."""
    from app.google.auth import GoogleAuthService
    from app.google.tasks import TasksService
    from app.config import get_settings
    
    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)
    credentials = await auth_service.get_credentials(user_id)
    
    if not credentials:
        await message.answer(
            "Для просмотра задач нужна авторизация в Google.\n"
            "Выполните /auth"
        )
        return
    
    try:
        tasks_service = TasksService()
        tasks = await tasks_service.list_tasks(
            credentials=credentials,
            max_results=20,
            show_completed=True,
        )
        
        if not tasks:
            text = "📋 Задачи на сегодня:\n\nСписок пуст!"
            keyboard = None
        else:
            lines = ["📋 Задачи на сегодня:\n"]
            buttons = []
            
            for task in tasks:
                status = task.get("status", "needsAction")
                title = task.get("title", "Без названия")
                task_id = task.get("id", "")
                
                if status == "completed":
                    checkbox = "✅"
                else:
                    checkbox = "⬜"
                
                lines.append(f"{checkbox} {title}")
                buttons.append([
                    InlineKeyboardButton(
                        text=f"{'✅' if status == 'completed' else '⬜'} {title[:30]}",
                        callback_data=f"toggle_task:{task_id}",
                    )
                ])
            
            text = "\n".join(lines)
            buttons.append([
                InlineKeyboardButton(text="🔄 Обновить", callback_data="tasks_today")
            ])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        if edit and message:
            await message.edit_text(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"Show tasks error: {e}")
        await message.answer("Ошибка при получении задач")


@router.message(Command("auth"))
async def handle_auth(message: Message, token_storage: TokenStorage) -> None:
    """
    Handle /auth command - initiate Google OAuth2.

    Args:
        message: Telegram message
        token_storage: Token storage from workflow_data
    """
    from app.google.auth import GoogleAuthService
    from app.config import get_settings

    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)

    user_id = message.from_user.id if message.from_user else 0

    # Check if already authorized
    if await auth_service.is_authorized(user_id):
        await message.answer(
            "✅ Вы уже авторизованы в Google!\n\n"
            "Если хотите переавторизоваться, сначала отвяжите аккаунт "
            "и повторите команду /auth."
        )
        return

    try:
        # Generate auth URL
        auth_url = await auth_service.get_auth_url(user_id)

        await message.answer(
            "🔐 Авторизация в Google\n\n"
            "1. Перейдите по ссылке ниже\n"
            "2. Войдите в свой Google аккаунт\n"
            "3. Разрешите доступ к календарю и задачам\n"
            "4. Скопируйте код и отправьте его мне\n\n"
            f"🔗 {auth_url}"
        )

    except FileNotFoundError:
        await message.answer(
            "⚠️ Файл credentials.json не найден.\n"
            "Обратитесь к администратору бота."
        )
    except Exception as e:
        logger.error(f"Auth error for user {user_id}: {e}")
        await message.answer(
            "⚠️ Ошибка при создании ссылки авторизации.\n"
            "Попробуйте позже."
        )


@router.message(Command("clear"))
async def handle_clear(message: Message, llm_client: LLMClient) -> None:
    """
    Handle /clear command - clear conversation history.

    Args:
        message: Telegram message
        llm_client: LLM client from workflow_data
    """
    user_id = message.from_user.id if message.from_user else 0
    await llm_client.clear_history(user_id)
    
    await message.answer("🗑 История диалога очищена.")


@router.message(F.text)
async def handle_text_message(
    message: Message,
    llm_client: LLMClient,
    token_storage: TokenStorage,
) -> None:
    """
    Handle all text messages - send to LLM.

    Args:
        message: Telegram message
        llm_client: LLM client from workflow_data
        token_storage: Token storage from workflow_data
    """
    if not message.text:
        return

    user_id = message.from_user.id if message.from_user else 0
    text = message.text

    # Check if this is an OAuth code (starts with 4/)
    if text.startswith("4/"):
        await handle_oauth_code(message, text, token_storage, llm_client)
        return

    # Show typing indicator
    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Get response from LLM (may retry on rate limit)
        response = await _get_llm_response_with_rate_limit_handling(
            message, llm_client, user_id, text
        )
        
        
        # Send response as plain text
        if len(response) > 4096:
            for i in range(0, len(response), 4096):
                await message.answer(response[i:i+4096])
        else:
            await message.answer(response)

    except Exception as e:
        logger.error(f"LLM error for user {user_id}: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обработке запроса.\n"
            "Попробуйте ещё раз или выполните /clear для сброса диалога."
        )


async def _get_llm_response_with_rate_limit_handling(
    message: Message,
    llm_client: LLMClient,
    user_id: int,
    text: str,
    max_retries: int = 3,
) -> str:
    """
    Get LLM response with rate limit handling.
    
    Notifies user about waiting and retries after delay.
    """
    import asyncio
    from app.llm.retry import RateLimitException
    
    for attempt in range(max_retries):
        try:
            return await llm_client.chat(user_id, text)
        except RateLimitException as e:
            if attempt < max_retries - 1:
                await message.answer(
                    f"⏳ Превышен лимит запросов. Подождите {int(e.retry_after)} секунд..."
                )
                await asyncio.sleep(e.retry_after)
                # Show typing again
                if message.bot:
                    await message.bot.send_chat_action(message.chat.id, "typing")
            else:
                raise Exception("Превышен лимит запросов. Попробуйте позже.")
    
    raise Exception("Не удалось получить ответ")


async def handle_oauth_code(
    message: Message,
    code: str,
    token_storage: TokenStorage,
    llm_client: LLMClient,
) -> None:
    """
    Handle OAuth authorization code.

    Args:
        message: Telegram message
        code: OAuth authorization code
        token_storage: Token storage
        llm_client: LLM client for clearing history
    """
    from app.google.auth import GoogleAuthService
    from app.config import get_settings

    user_id = message.from_user.id if message.from_user else 0
    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)

    try:
        success = await auth_service.handle_callback(user_id, code)
        
        if success:
            # Clear chat history after successful auth
            await llm_client.clear_history(user_id)
            
            await message.answer(
                "✅ Авторизация успешна!\n\n"
                "Теперь я могу работать с вашим календарём и задачами.\n"
                "Попробуйте спросить: Какие у меня события на сегодня?"
            )
        else:
            await message.answer(
                "⚠️ Не удалось завершить авторизацию.\n"
                "Попробуйте выполнить /auth заново."
            )

    except Exception as e:
        logger.error(f"OAuth callback error for user {user_id}: {e}")
        await message.answer(
            "⚠️ Ошибка при обработке кода авторизации.\n"
            "Попробуйте выполнить /auth заново."
        )
