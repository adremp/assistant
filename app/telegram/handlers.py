"""Telegram message handlers."""

import logging
import re
from typing import Any
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.llm.client import LLMClient
from app.storage.tokens import TokenStorage
from app.storage.pending_responses import PendingResponseStorage
from app.storage.pending_reminder_confirm import PendingReminderConfirmation
from app.storage.reminders import ReminderStorage
from app.scheduler.service import ReminderScheduler

logger = logging.getLogger(__name__)

router = Router(name="main")


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Get main menu keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Задачи на сегодня", callback_data="tasks_today")],
        [InlineKeyboardButton(text="📅 События на сегодня", callback_data="events_today")],
        [InlineKeyboardButton(text="⏰ Мои напоминания", callback_data="my_reminders")],
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
        "/reminders — мои напоминания\n"
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
        "- Добавь задачу купить молоко\n"
        "- Напоминай каждый день в 20:00 как прошёл день\n\n"
        "Команды:\n"
        "/start — начать работу\n"
        "/auth — авторизация в Google\n"
        "/tasks — задачи на сегодня\n"
        "/reminders — мои напоминания\n"
        "/timezone — обновить часовой пояс\n"
        "/clear — очистить историю диалога"
    )


@router.message(Command("timezone"))
async def cmd_timezone(message: Message, token_storage: TokenStorage) -> None:
    """Update user timezone from Google Calendar settings."""
    from app.google.auth import GoogleAuthService
    from app.google.calendar import CalendarService
    from app.config import get_settings

    user_id = message.from_user.id if message.from_user else 0
    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)
    
    credentials = await auth_service.get_credentials(user_id)
    if not credentials:
        await message.answer(
            "⚠️ Требуется авторизация в Google.\n"
            "Выполните /auth для авторизации."
        )
        return
    
    try:
        calendar_service = CalendarService()
        user_timezone = await calendar_service.get_user_timezone(credentials)
        await token_storage.set_user_timezone(user_id, user_timezone)
        
        await message.answer(
            f"✅ Часовой пояс обновлён\n\n"
            f"🌍 Текущий часовой пояс: **{user_timezone}**"
        )
    except Exception as e:
        logger.error(f"Timezone update error: {e}")
        await message.answer("⚠️ Ошибка при обновлении часового пояса.")


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


@router.message(Command("reminders"))
async def handle_reminders_command(
    message: Message,
    reminder_scheduler: ReminderScheduler,
) -> None:
    """Handle /reminders command - show active reminders."""
    user_id = message.from_user.id if message.from_user else 0
    await show_user_reminders(message, user_id, reminder_scheduler)


async def show_user_reminders(
    message: Message,
    user_id: int,
    reminder_scheduler: ReminderScheduler,
    edit: bool = False,
) -> None:
    """Show user's active reminders with delete buttons."""
    reminders = await reminder_scheduler.get_user_reminders(user_id)
    
    if not reminders:
        text = "⏰ Ваши напоминания:\n\nСписок пуст!"
        keyboard = None
    else:
        lines = ["⏰ Ваши напоминания:\n"]
        buttons = []
        
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        
        for reminder in reminders:
            reminder_id = reminder.get("id", "")
            template = reminder.get("template", "Без текста")
            schedule_type = reminder.get("schedule_type", "daily")
            time_str = reminder.get("time", "--:--")
            weekday = reminder.get("weekday")
            
            if schedule_type == "daily":
                schedule_info = f"Ежедневно в {time_str}"
            else:
                day_name = weekdays[weekday] if weekday is not None else "?"
                schedule_info = f"Кажд. {day_name} в {time_str}"
            
            # Truncate template for display
            template_short = template[:40] + "..." if len(template) > 40 else template
            lines.append(f"• {template_short}\n  🕒 {schedule_info}")
        
        text = "\n".join(lines)
        buttons.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data="my_reminders")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if edit and message:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


@router.message(F.text)
async def handle_text_message(
    message: Message,
    llm_client: LLMClient,
    token_storage: TokenStorage,
    pending_storage: PendingResponseStorage,
) -> None:
    """
    Handle all text messages - check for pending reminder or send to LLM.

    Args:
        message: Telegram message
        llm_client: LLM client from workflow_data
        token_storage: Token storage from workflow_data
        pending_storage: Pending response storage
    """
    if not message.text:
        return

    user_id = message.from_user.id if message.from_user else 0
    text = message.text

    # Check if this is an OAuth code (starts with 4/)
    if text.startswith("4/"):
        await handle_oauth_code(message, text, token_storage, llm_client)
        return

    # Check for pending reminder response
    pending = await pending_storage.get_pending(user_id)
    if pending:
        await _handle_reminder_response(
            message, user_id, text, pending, pending_storage, token_storage
        )
        return

    # Show typing indicator
    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Get response from LLM (may retry on rate limit)
        response = await _get_llm_response_with_rate_limit_handling(
            message, llm_client, user_id, text, token_storage
        )
        
        # Handle confirmation responses with buttons
        if isinstance(response, dict) and response.get("type") == "needs_confirmation":
            confirmation_id = response.get("confirmation_id", "")
            msg_text = response.get("message", "Подтвердите действие")
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Подтвердить",
                        callback_data=f"confirm_reminder:{confirmation_id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=f"cancel_reminder:{confirmation_id}"
                    ),
                ]
            ])
            await message.answer(msg_text, reply_markup=keyboard)
            return
        
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
    token_storage: TokenStorage | None = None,
    max_retries: int = 3,
) -> str:
    """
    Get LLM response with rate limit handling.
    
    Notifies user about waiting and retries after delay.
    """
    import asyncio
    from app.llm.retry import RateLimitException
    user_timezone = None
    if token_storage:
        try:
            user_timezone = await token_storage.get_user_timezone(user_id)
        except Exception as e:
            logger.warning(f"Failed to get user timezone for {user_id}: {e}")

    for attempt in range(max_retries):
        try:
            return await llm_client.chat(user_id, text, user_timezone=user_timezone)
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


@router.message(F.voice)
async def handle_voice_message(
    message: Message,
    llm_client: LLMClient,
    pending_storage: PendingResponseStorage,
    token_storage: TokenStorage,
) -> None:
    """
    Handle voice messages - transcribe and check for pending reminder or send to LLM.

    Args:
        message: Telegram message with voice
        llm_client: LLM client from workflow_data
        pending_storage: Pending response storage
        token_storage: Token storage for Google auth
    """
    from app.llm.transcription import TranscriptionService
    from app.config import get_settings
    
    user_id = message.from_user.id if message.from_user else 0
    voice = message.voice
    
    if not voice or not message.bot:
        return

    # Show typing indicator
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Download voice file
        file = await message.bot.get_file(voice.file_id)
        if not file.file_path:
            await message.answer("⚠️ Не удалось получить аудио файл.")
            return
        
        # Download file content
        file_bytes = await message.bot.download_file(file.file_path)
        if not file_bytes:
            await message.answer("⚠️ Не удалось скачать аудио файл.")
            return
        
        audio_data = file_bytes.read()
        
        # Transcribe audio
        settings = get_settings()
        transcription_service = TranscriptionService(settings)
        
        try:
            transcribed_text = await transcription_service.transcribe(audio_data, "voice.ogg")
        except Exception as e:
            logger.error(f"Transcription failed for user {user_id}: {e}")
            await message.answer("⚠️ Не удалось распознать голосовое сообщение.")
            return
        
        if not transcribed_text:
            await message.answer("⚠️ Не удалось распознать речь в сообщении.")
            return
        
        # Show what was recognized
        await message.answer(f"� Распознано: {transcribed_text}")
        
        # Check for pending reminder response
        pending = await pending_storage.get_pending(user_id)
        if pending:
            await _handle_reminder_response(
                message, user_id, transcribed_text, pending, pending_storage, token_storage
            )
            return
        
        # Show typing indicator again
        await message.bot.send_chat_action(message.chat.id, "typing")
        
        # Send transcribed text to LLM (will be saved to history as user message)
        response = await _get_llm_response_with_rate_limit_handling(
            message, llm_client, user_id, transcribed_text, token_storage
        )
        
        # Send response
        if len(response) > 4096:
            for i in range(0, len(response), 4096):
                await message.answer(response[i:i+4096])
        else:
            await message.answer(response)

    except Exception as e:
        logger.error(f"Voice message error for user {user_id}: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обработке голосового сообщения.\n"
            "Попробуйте ещё раз."
        )

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
    from app.google.calendar import CalendarService
    from app.config import get_settings

    user_id = message.from_user.id if message.from_user else 0
    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)

    try:
        success = await auth_service.handle_callback(user_id, code)
        
        if success:
            # Get user's timezone from Google Calendar
            credentials = await auth_service.get_credentials(user_id)
            if credentials:
                calendar_service = CalendarService()
                user_timezone = await calendar_service.get_user_timezone(credentials)
                await token_storage.set_user_timezone(user_id, user_timezone)
                logger.info(f"Saved user timezone: {user_timezone}")
            
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


async def _handle_reminder_response(
    message: Message,
    user_id: int,
    response_text: str,
    pending: dict,
    pending_storage: PendingResponseStorage,
    token_storage: TokenStorage,
) -> None:
    """Handle user's response to a reminder by creating a completed Google Task."""
    from app.google.auth import GoogleAuthService
    from app.google.tasks import TasksService
    from app.config import get_settings
    
    reminder_id = pending.get("reminder_id", "")
    template = pending.get("template", "")
    
    # Clear pending state first
    await pending_storage.clear_pending(user_id)
    
    # Try to save as completed Google Task
    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)
    credentials = await auth_service.get_credentials(user_id)
    
    if credentials:
        try:
            tasks_service = TasksService()
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            task_title = f"📝 {template}"
            task_notes = f"Ответ ({now}):\n{response_text}"
            
            await tasks_service.create_completed_task(
                credentials=credentials,
                title=task_title,
                notes=task_notes,
            )
            
            await message.answer(
                "✅ Ответ сохранён в Google Tasks!\n\n"
                f"📝 Шаблон: {template}\n"
                f"💬 Ответ: {response_text}"
            )
            logger.info(f"Created completed task for reminder {reminder_id}, user {user_id}")
        except Exception as e:
            logger.error(f"Failed to create task for reminder response: {e}")
            await message.answer(
                "⚠️ Не удалось сохранить в Google Tasks.\n\n"
                f"📝 Шаблон: {template}\n"
                f"💬 Ответ: {response_text}"
            )
    else:
        await message.answer(
            "⚠️ Требуется авторизация в Google (/auth) для сохранения ответа.\n\n"
            f"📝 Шаблон: {template}\n"
            f"💬 Ответ: {response_text}"
        )


@router.callback_query(F.data == "my_reminders")
async def handle_my_reminders_callback(
    callback: CallbackQuery,
    reminder_scheduler: ReminderScheduler,
) -> None:
    """Handle my_reminders button click."""
    await callback.answer()
    user_id = callback.from_user.id
    await show_user_reminders(callback.message, user_id, reminder_scheduler, edit=True)


@router.callback_query(F.data.startswith("confirm_reminder:"))
async def handle_confirm_reminder(
    callback: CallbackQuery,
    pending_confirm: PendingReminderConfirmation,
    reminder_storage: ReminderStorage,
    reminder_scheduler: ReminderScheduler,
    token_storage: TokenStorage,
) -> None:
    """Handle reminder confirmation."""
    from app.google.calendar import CalendarService
    from app.google.auth import GoogleAuthService
    from app.config import get_settings
    from app.constants import REMINDER_TAG
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    await callback.answer("Создаю напоминание...")
    
    confirmation_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    # Get pending data
    pending_data = await pending_confirm.get_pending(confirmation_id)
    if not pending_data:
        await callback.message.edit_text("⚠️ Срок подтверждения истёк. Создайте напоминание заново.")
        return
    
    # Verify user
    if pending_data.get("user_id") != user_id:
        await callback.message.answer("⚠️ Это подтверждение предназначено для другого пользователя.")
        return
    
    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)
    calendar_service = CalendarService()
    
    credentials = await auth_service.get_credentials(user_id)
    if not credentials:
        await callback.message.edit_text("⚠️ Требуется авторизация. Выполните /auth")
        return
    
    try:
        template = pending_data["template"]
        schedule_type = pending_data["schedule_type"]
        time_str = pending_data["time"]
        timezone = pending_data["timezone"]
        weekday = pending_data.get("weekday")
        summary = pending_data.get("summary")
        
        # Parse time
        hour, minute = map(int, time_str.split(":"))
        
        # Create title
        event_summary = summary or template[:50] + ("..." if len(template) > 50 else "")
        
        # Build description with tag
        event_description = f"{REMINDER_TAG} {template}"
        
        # Build recurrence rule
        if schedule_type == "daily":
            recurrence = ["RRULE:FREQ=DAILY"]
        else:
            weekday_map = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
            day_code = weekday_map[weekday] if weekday is not None else "MO"
            recurrence = [f"RRULE:FREQ=WEEKLY;BYDAY={day_code}"]
        
        # Calculate start/end times
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        start_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if start_dt <= now:
            start_dt += timedelta(days=1)
        
        if schedule_type == "weekly" and weekday is not None:
            days_ahead = weekday - start_dt.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            start_dt += timedelta(days=days_ahead)
        
        end_dt = start_dt + timedelta(minutes=15)
        
        # Create Google Calendar event
        event = await calendar_service.create_event(
            credentials=credentials,
            summary=f"⏰ {event_summary}",
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
            description=event_description,
            recurrence=recurrence,
            timezone=timezone,
        )
        
        calendar_event_id = event.get("id", "")
        
        # Save to Redis
        reminder_id = await reminder_storage.save_reminder(
            user_id=user_id,
            template=template,
            schedule_type=schedule_type,
            time=time_str,
            timezone=timezone,
            weekday=weekday,
            calendar_event_id=calendar_event_id,
        )
        
        # Schedule in APScheduler
        reminder = await reminder_storage.get_reminder(reminder_id)
        if reminder:
            await reminder_scheduler._schedule_reminder(reminder)
        
        # Clean up
        await pending_confirm.delete_pending(confirmation_id)
        
        weekdays = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
        if schedule_type == "daily":
            schedule_desc = f"ежедневно в {time_str}"
        else:
            day_name = weekdays[weekday] if weekday is not None else "?"
            schedule_desc = f"каждый {day_name} в {time_str}"
        
        await callback.message.edit_text(
            f"✅ Напоминание создано!\n\n"
            f"📝 {template}\n"
            f"⏰ {schedule_desc}\n"
            f"🌍 {timezone}"
        )
        
    except Exception as e:
        logger.error(f"Error creating reminder: {e}")
        await callback.message.edit_text(f"⚠️ Ошибка при создании напоминания: {str(e)}")


@router.callback_query(F.data.startswith("cancel_reminder:"))
async def handle_cancel_reminder(
    callback: CallbackQuery,
    pending_confirm: PendingReminderConfirmation,
) -> None:
    """Handle reminder cancellation."""
    await callback.answer("Отменено")
    
    confirmation_id = callback.data.split(":")[1]
    await pending_confirm.delete_pending(confirmation_id)
    
    await callback.message.edit_text("❌ Создание напоминания отменено.")

