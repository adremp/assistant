"""Telegram message handlers."""

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.llm.client import LLMClient
from app.scheduler.service import ReminderScheduler
from app.storage.pending_reminder_confirm import PendingReminderConfirmation
from app.storage.reminders import ReminderStorage
from app.storage.summary_groups import SummaryGroupStorage
from app.storage.tokens import TokenStorage

logger = logging.getLogger(__name__)

router = Router(name="main")


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Get main menu keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Задачи на сегодня", callback_data="tasks_today"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 События на сегодня", callback_data="events_today"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏰ Мои напоминания", callback_data="my_reminders"
                )
            ],
            [InlineKeyboardButton(text="📊 Сводки", callback_data="summaries_menu")],
        ]
    )


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
        "/notion_setup — настройка Notion\n"
        "/telethon_auth — авторизация для каналов\n"
        "/summaries — сводки\n"
        "/tasks — задачи на сегодня\n"
        "/reminders — мои напоминания\n"
        "/timezone — обновить часовой пояс\n"
        "/clear — очистить историю диалога"
    )


@router.message(Command("timezone"))
async def cmd_timezone(message: Message, token_storage: TokenStorage) -> None:
    """Update user timezone from Google Calendar settings."""
    from app.config import get_settings
    from app.google.auth import GoogleAuthService
    from app.google.calendar import CalendarService

    user_id = message.from_user.id if message.from_user else 0
    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)

    credentials = await auth_service.get_credentials(user_id)
    if not credentials:
        await message.answer(
            "⚠️ Требуется авторизация в Google.\nВыполните /auth для авторизации."
        )
        return

    try:
        calendar_service = CalendarService()
        user_timezone = await calendar_service.get_user_timezone(credentials)
        await token_storage.set_user_timezone(user_id, user_timezone)

        await message.answer(
            f"✅ Часовой пояс обновлён\n\n🌍 Текущий часовой пояс: **{user_timezone}**"
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
    from app.config import get_settings
    from app.google.auth import GoogleAuthService
    from app.google.tasks import TasksService

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
    from app.config import get_settings
    from app.google.auth import GoogleAuthService
    from app.google.tasks import TasksService

    settings = get_settings()
    auth_service = GoogleAuthService(settings, token_storage)
    credentials = await auth_service.get_credentials(user_id)

    if not credentials:
        await message.answer(
            "Для просмотра задач нужна авторизация в Google.\nВыполните /auth"
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
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"{'✅' if status == 'completed' else '⬜'} {title[:30]}",
                            callback_data=f"toggle_task:{task_id}",
                        )
                    ]
                )

            text = "\n".join(lines)
            buttons.append(
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="tasks_today")]
            )
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
    """Handle /auth command - initiate Google OAuth2."""
    from app.config import get_settings
    from app.google.auth import GoogleAuthService

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
        auth_url = await auth_service.get_auth_url(user_id)

        await message.answer(
            "🔐 Авторизация в Google\n\n"
            "Нажмите кнопку ниже, чтобы войти в Google.\n"
            "После подтверждения вы автоматически вернётесь сюда.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔗 Войти в Google", url=auth_url)]
                ]
            ),
        )

    except FileNotFoundError:
        await message.answer(
            "⚠️ Файл credentials.json не найден.\nОбратитесь к администратору бота."
        )
    except ValueError as e:
        logger.error(f"Auth config error: {e}")
        await message.answer(
            "⚠️ Google OAuth не настроен.\nТребуется GOOGLE_REDIRECT_URI в .env"
        )
    except Exception as e:
        logger.error(f"Auth error for user {user_id}: {e}")
        await message.answer("⚠️ Ошибка авторизации. Попробуйте позже.")


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


# Notion setup state storage
_notion_setup_state: dict[int, dict] = {}


@router.message(Command("notion_setup"))
async def handle_notion_setup(
    message: Message,
    token_storage: TokenStorage,
) -> None:
    """Handle /notion_setup command - configure per-user Notion integration."""
    user_id = message.from_user.id if message.from_user else 0

    # Check if already configured
    existing_token = await token_storage.get_notion_token(user_id)

    if existing_token:
        await message.answer(
            "📝 Notion уже настроен!\n\nХотите изменить настройки?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔄 Перенастроить", callback_data="notion_reconfigure"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🗑 Удалить интеграцию", callback_data="notion_clear"
                        )
                    ],
                ]
            ),
        )
        return

    # Start setup
    _notion_setup_state[user_id] = {
        "step": "token",
    }

    await message.answer(
        "📝 Настройка Notion (персональная)\n\n"
        "1. Создайте интеграцию: https://www.notion.so/my-integrations\n"
        "2. Скопируйте Internal Integration Token\n"
        "3. Отправьте токен сюда\n\n"
        "⚠️ Токен будет привязан только к вашему аккаунту."
    )


@router.callback_query(F.data == "notion_reconfigure")
async def handle_notion_reconfigure(callback: CallbackQuery) -> None:
    """Start Notion reconfiguration."""
    await callback.answer()
    user_id = callback.from_user.id

    _notion_setup_state[user_id] = {"step": "token"}

    await callback.message.edit_text(
        "📝 Перенастройка Notion\n\nОтправьте новый токен интеграции:"
    )


@router.callback_query(F.data == "notion_clear")
async def handle_notion_clear(
    callback: CallbackQuery,
    token_storage: TokenStorage,
) -> None:
    """Clear Notion integration."""
    await callback.answer("Интеграция удалена")
    user_id = callback.from_user.id

    # Clear tokens
    token_data = await token_storage.load_token(user_id)
    if token_data:
        token_data.pop("notion_token", None)
        token_data.pop("notion_parent_page_id", None)
        token_data.pop("notion_completed_tasks_page_id", None)
        await token_storage.save_token(user_id, token_data)

    await callback.message.edit_text("✅ Интеграция с Notion удалена.")


async def process_notion_setup_input(
    message: Message,
    token_storage: TokenStorage,
) -> bool:
    """Process text input during Notion setup."""
    user_id = message.from_user.id if message.from_user else 0
    state = _notion_setup_state.get(user_id)

    if not state:
        return False

    text = message.text.strip() if message.text else ""

    if state["step"] == "token":
        # Validate token format
        if not text.startswith("secret_") or len(text) < 20:
            await message.answer(
                "⚠️ Токен должен начинаться с 'secret_'\nПопробуйте скопировать ещё раз."
            )
            return True

        state["token"] = text
        state["step"] = "parent_page"

        await message.answer(
            "✅ Токен принят!\n\n"
            "Теперь создайте страницу для сохранения сводок:\n"
            "1. Создайте новую страницу в Notion\n"
            "2. Дайте интеграции доступ к этой странице\n"
            "3. Скопируйте ID страницы из URL\n\n"
            "Пример URL:\n"
            "notion.so/My-Page-**abc123def456**\n\n"
            "Отправьте ID страницы:"
        )
        return True

    elif state["step"] == "parent_page":
        # Clean page ID (remove hyphens and take last part if full URL)
        page_id = text.replace("-", "").strip()
        if "/" in page_id:
            page_id = page_id.split("/")[-1].split("-")[-1]

        if len(page_id) < 20:
            await message.answer(
                "⚠️ ID страницы слишком короткий.\n"
                "Скопируйте ID из URL страницы в Notion."
            )
            return True

        # Save configuration
        await token_storage.set_notion_token(user_id, state["token"])
        await token_storage.set_notion_parent_page_id(user_id, page_id)

        del _notion_setup_state[user_id]

        await message.answer(
            "✅ Notion настроен!\n\n"
            "Теперь сводки по выполненным задачам будут сохраняться\n"
            "в вашу персональную страницу Notion."
        )
        return True

    return False


# Telethon auth state storage
_telethon_auth_state: dict[int, dict] = {}


@router.message(Command("telethon_auth"))
async def handle_telethon_auth(
    message: Message,
    token_storage: TokenStorage,
) -> None:
    """Handle /telethon_auth command - initiate per-user Telethon authorization."""
    from app.config import get_settings
    from app.telegram.telethon_service import TelethonService

    user_id = message.from_user.id if message.from_user else 0
    settings = get_settings()

    # Load user's existing session
    session_string = await token_storage.get_telethon_session(user_id)
    telethon_service = TelethonService(settings, session_string)

    if not telethon_service.is_configured:
        await message.answer(
            "⚠️ Telethon не настроен.\n\n"
            "Администратор должен добавить TELETHON_API_ID и TELETHON_API_HASH.\n"
            "Получить можно на https://my.telegram.org/apps"
        )
        return

    if session_string and await telethon_service.is_authorized():
        await message.answer(
            "✅ Вы уже авторизованы в Telethon!\n\nМожете использовать функцию сводок.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔄 Переавторизоваться",
                            callback_data="telethon_reauth",
                        )
                    ],
                ]
            ),
        )
        return

    # Initialize auth state (we'll create service per message to maintain session)
    _telethon_auth_state[user_id] = {
        "step": "phone",
        "phone": None,
        "phone_code_hash": None,
        "service": telethon_service,  # Keep service instance for session continuity
    }

    await message.answer(
        "🔐 Авторизация Telethon (персональная)\n\n"
        "Ваша сессия будет привязана только к вашему аккаунту.\n\n"
        "Введите номер телефона в формате +79001234567:"
    )


@router.callback_query(F.data == "telethon_reauth")
async def handle_telethon_reauth(
    callback: CallbackQuery,
    token_storage: TokenStorage,
) -> None:
    """Clear session and restart auth."""
    await callback.answer()
    user_id = callback.from_user.id

    await token_storage.clear_telethon_session(user_id)

    # Show auth prompt
    _telethon_auth_state[user_id] = {
        "step": "phone",
        "phone": None,
        "phone_code_hash": None,
        "service": None,  # Will create fresh
    }

    await callback.message.edit_text(
        "🔐 Переавторизация Telethon\n\nВведите номер телефона в формате +79001234567:"
    )


async def process_telethon_auth_input(
    message: Message,
    token_storage: TokenStorage,
) -> bool:
    """
    Process text input during Telethon auth.

    Returns True if handled, False otherwise.
    """
    from app.config import get_settings
    from app.telegram.telethon_service import TelethonService

    user_id = message.from_user.id if message.from_user else 0
    state = _telethon_auth_state.get(user_id)

    if not state:
        return False

    text = message.text.strip() if message.text else ""
    settings = get_settings()

    # Get or create service
    telethon_service = state.get("service")
    if telethon_service is None:
        telethon_service = TelethonService(settings)
        state["service"] = telethon_service

    if state["step"] == "phone":
        # Validate phone format
        if not text.startswith("+") or len(text) < 10:
            await message.answer(
                "⚠️ Неверный формат номера.\nВведите номер в формате +79001234567:"
            )
            return True

        try:
            phone_code_hash = await telethon_service.send_code(text)
            state["phone"] = text
            state["phone_code_hash"] = phone_code_hash
            state["step"] = "code"

            await message.answer(
                "✅ Код отправлен!\n\nВведите код из SMS или Telegram:"
            )
        except Exception as e:
            logger.error(f"Telethon send_code failed: {e}")
            await message.answer(f"⚠️ Ошибка отправки кода: {str(e)[:100]}")
            del _telethon_auth_state[user_id]

        return True

    elif state["step"] == "code":
        try:
            session_string = await telethon_service.sign_in(
                state["phone"],
                text,
                state["phone_code_hash"],
            )

            del _telethon_auth_state[user_id]

            if session_string:
                # Save session to user's storage
                await token_storage.set_telethon_session(user_id, session_string)
                await message.answer(
                    "✅ Telethon авторизован!\n\n"
                    "Ваша персональная сессия сохранена.\n"
                    "Теперь вы можете использовать функцию сводок (/summaries)."
                )
            else:
                await message.answer(
                    "⚠️ Ошибка авторизации. Попробуйте снова (/telethon_auth)."
                )
        except Exception as e:
            logger.error(f"Telethon sign_in failed: {e}")
            await message.answer(f"⚠️ Ошибка авторизации: {str(e)[:100]}")
            del _telethon_auth_state[user_id]

        return True

    return False


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
        buttons.append(
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="my_reminders")]
        )
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
    summary_group_storage: SummaryGroupStorage,
) -> None:
    """
    Handle all text messages - route to appropriate handler or LLM.

    Args:
        message: Telegram message
        llm_client: LLM client from workflow_data
        token_storage: Token storage from workflow_data
        summary_group_storage: Summary group storage
    """
    if not message.text:
        return

    user_id = message.from_user.id if message.from_user else 0
    text = message.text

    # Check for Telethon auth state
    if await process_telethon_auth_input(message, token_storage):
        return

    # Check for Notion setup state
    if await process_notion_setup_input(message, token_storage):
        return

    # Check for summary creation state
    if await process_summary_creation_input(message, summary_group_storage):
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

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Подтвердить",
                            callback_data=f"confirm_reminder:{confirmation_id}",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отмена",
                            callback_data=f"cancel_reminder:{confirmation_id}",
                        ),
                    ]
                ]
            )
            await message.answer(msg_text, reply_markup=keyboard)
            return

        # Handle auth_required - send constant message without adding to history
        if isinstance(response, dict) and response.get("type") == "auth_required":
            await message.answer(response.get("message", ""))
            return

        # Send response as plain text
        if len(response) > 4096:
            for i in range(0, len(response), 4096):
                await message.answer(response[i : i + 4096])
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
    token_storage: TokenStorage,
) -> None:
    """Handle voice messages - transcribe and send to LLM."""
    from app.config import get_settings
    from app.llm.transcription import TranscriptionService

    user_id = message.from_user.id if message.from_user else 0
    voice = message.voice

    if not voice or not message.bot:
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        file = await message.bot.get_file(voice.file_id)
        if not file.file_path:
            await message.answer("⚠️ Не удалось получить аудио файл.")
            return

        file_bytes = await message.bot.download_file(file.file_path)
        if not file_bytes:
            await message.answer("⚠️ Не удалось скачать аудио файл.")
            return

        audio_data = file_bytes.read()

        settings = get_settings()
        transcription_service = TranscriptionService(settings)

        try:
            transcribed_text = await transcription_service.transcribe(
                audio_data, "voice.ogg"
            )
        except Exception as e:
            logger.error(f"Transcription failed for user {user_id}: {e}")
            await message.answer("⚠️ Не удалось распознать голосовое сообщение.")
            return

        if not transcribed_text:
            await message.answer("⚠️ Не удалось распознать речь в сообщении.")
            return

        await message.answer(f"🎤 Распознано: {transcribed_text}")

        await message.bot.send_chat_action(message.chat.id, "typing")

        response = await _get_llm_response_with_rate_limit_handling(
            message, llm_client, user_id, transcribed_text, token_storage
        )

        # Handle confirmation responses with buttons
        if isinstance(response, dict) and response.get("type") == "needs_confirmation":
            confirmation_id = response.get("confirmation_id", "")
            msg_text = response.get("message", "Подтвердите действие")

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Подтвердить",
                            callback_data=f"confirm_reminder:{confirmation_id}",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отмена",
                            callback_data=f"cancel_reminder:{confirmation_id}",
                        ),
                    ]
                ]
            )
            await message.answer(msg_text, reply_markup=keyboard)
            return

        # Handle auth_required - send constant message without adding to history
        if isinstance(response, dict) and response.get("type") == "auth_required":
            await message.answer(response.get("message", ""))
            return

        if len(response) > 4096:
            for i in range(0, len(response), 4096):
                await message.answer(response[i : i + 4096])
        else:
            await message.answer(response)

    except Exception as e:
        logger.error(f"Voice message error for user {user_id}: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обработке голосового сообщения.\n"
            "Попробуйте ещё раз."
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
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from app.config import get_settings
    from app.constants import REMINDER_TAG
    from app.google.auth import GoogleAuthService
    from app.google.calendar import CalendarService

    await callback.answer("Создаю напоминание...")

    confirmation_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    # Get pending data
    pending_data = await pending_confirm.get_pending(confirmation_id)
    if not pending_data:
        await callback.message.edit_text(
            "⚠️ Срок подтверждения истёк. Создайте напоминание заново."
        )
        return

    # Verify user
    if pending_data.get("user_id") != user_id:
        await callback.message.answer(
            "⚠️ Это подтверждение предназначено для другого пользователя."
        )
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

        weekdays = [
            "понедельник",
            "вторник",
            "среду",
            "четверг",
            "пятницу",
            "субботу",
            "воскресенье",
        ]
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


# ==================== SUMMARY HANDLERS ====================


@router.message(Command("summaries"))
async def handle_summaries_command(
    message: Message,
    summary_group_storage: SummaryGroupStorage,
    token_storage: TokenStorage,
) -> None:
    """Handle /summaries command - show summary groups menu."""
    user_id = message.from_user.id if message.from_user else 0
    await show_summaries_menu(message, user_id, summary_group_storage, token_storage)


@router.callback_query(F.data == "summaries_menu")
async def handle_summaries_menu_callback(
    callback: CallbackQuery,
    summary_group_storage: SummaryGroupStorage,
    token_storage: TokenStorage,
) -> None:
    """Handle summaries menu button click."""
    await callback.answer()
    user_id = callback.from_user.id
    await show_summaries_menu(
        callback.message, user_id, summary_group_storage, token_storage, edit=True
    )


async def show_summaries_menu(
    message: Message,
    user_id: int,
    summary_group_storage: SummaryGroupStorage,
    token_storage: TokenStorage | None = None,
    edit: bool = False,
) -> None:
    """Show summary groups menu."""
    # Check Telethon authorization
    if token_storage:
        session_string = await token_storage.get_telethon_session(user_id)
        if not session_string:
            text = (
                "⚠️ Для работы со сводками требуется авторизация в Telegram.\n\n"
                "Используйте команду /telethon_auth для авторизации."
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="back_to_main"
                        )
                    ]
                ]
            )
            if edit and message:
                await message.edit_text(text, reply_markup=keyboard)
            elif message:
                await message.answer(text, reply_markup=keyboard)
            return

    groups = await summary_group_storage.get_user_groups(user_id)

    buttons = []

    if groups:
        text = "📊 Ваши группы сводок:\n\n"
        for group in groups:
            group_id = group.get("id", "")
            name = group.get("name", "Без названия")
            channels_count = len(group.get("channel_ids", []))
            text += f"• {name} ({channels_count} каналов)\n"
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"📄 {name}",
                        callback_data=f"run_summary:{group_id}",
                    ),
                    InlineKeyboardButton(
                        text="✏️",
                        callback_data=f"edit_summary:{group_id}",
                    ),
                    InlineKeyboardButton(
                        text="🗑",
                        callback_data=f"delete_summary:{group_id}",
                    ),
                ]
            )
    else:
        text = "📊 Сводки\n\nУ вас пока нет групп сводок."

    # Static completed tasks button
    buttons.append(
        [
            InlineKeyboardButton(
                text="✅ Выполненные задачи", callback_data="completed_tasks_summary"
            )
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text="➕ Создать группу", callback_data="create_summary_group"
            )
        ]
    )
    buttons.append(
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    if edit and message:
        try:
            await message.edit_text(text, reply_markup=keyboard)
        except Exception:
            await message.answer(text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "back_to_main")
async def handle_back_to_main(callback: CallbackQuery) -> None:
    """Handle back to main menu."""
    await callback.answer()
    await callback.message.edit_text(
        "🏠 Главное меню",
        reply_markup=get_main_keyboard(),
    )


# Summary creation state storage (in-memory, keyed by user_id)
_summary_creation_state: dict[int, dict] = {}


@router.callback_query(F.data == "create_summary_group")
async def handle_create_summary_group(callback: CallbackQuery) -> None:
    """Start summary group creation flow."""
    await callback.answer()
    user_id = callback.from_user.id

    # Initialize creation state
    _summary_creation_state[user_id] = {
        "step": "name",
        "name": None,
        "prompt": None,
        "channel_ids": [],
    }

    await callback.message.edit_text(
        "📝 Создание группы сводок\n\nШаг 1/3: Введите название группы:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Отмена", callback_data="cancel_summary_creation"
                    )
                ]
            ]
        ),
    )


@router.callback_query(F.data == "cancel_summary_creation")
async def handle_cancel_summary_creation(
    callback: CallbackQuery,
    summary_group_storage: SummaryGroupStorage,
    token_storage: TokenStorage,
) -> None:
    """Cancel summary group creation."""
    await callback.answer("Отменено")
    user_id = callback.from_user.id

    if user_id in _summary_creation_state:
        del _summary_creation_state[user_id]

    await show_summaries_menu(
        callback.message, user_id, summary_group_storage, token_storage, edit=True
    )


@router.callback_query(F.data == "finish_channel_selection")
async def handle_finish_channel_selection(
    callback: CallbackQuery,
    summary_group_storage: SummaryGroupStorage,
) -> None:
    """Finish channel selection and create the summary group."""
    await callback.answer()
    user_id = callback.from_user.id

    state = _summary_creation_state.get(user_id)
    if not state:
        await callback.message.edit_text("⚠️ Сессия создания истекла. Попробуйте снова.")
        return

    if not state.get("channel_ids"):
        await callback.message.edit_text(
            "⚠️ Добавьте хотя бы один канал!\n\n"
            "Отправьте username канала (например: @channel или channel):",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Отмена", callback_data="cancel_summary_creation"
                        )
                    ]
                ]
            ),
        )
        return

    # Create the group
    group_id = await summary_group_storage.create_group(
        user_id=user_id,
        name=state["name"],
        prompt=state["prompt"],
        channel_ids=state["channel_ids"],
    )

    # Clean up state
    del _summary_creation_state[user_id]

    await callback.message.edit_text(
        f"✅ Группа сводок создана!\n\n"
        f"📁 {state['name']}\n"
        f"📝 Промпт: {state['prompt'][:50]}...\n"
        f"📺 Каналов: {len(state['channel_ids'])}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 К сводкам", callback_data="summaries_menu"
                    )
                ]
            ]
        ),
    )


@router.callback_query(F.data.startswith("toggle_channel:"))
async def handle_toggle_channel(callback: CallbackQuery) -> None:
    """Toggle channel selection in summary group creation."""
    await callback.answer()
    user_id = callback.from_user.id

    state = _summary_creation_state.get(user_id)
    if not state or state.get("step") != "channels":
        return

    channel_id = callback.data.split(":", 1)[1]

    # Toggle selection
    if channel_id in state["channel_ids"]:
        state["channel_ids"].remove(channel_id)
    else:
        state["channel_ids"].append(channel_id)

    # Rebuild buttons
    buttons = []
    for ch in state.get("available_channels", [])[:30]:
        ch_id = ch.get("username") or str(ch.get("id"))
        title = ch.get("title", "Unknown")[:25]
        is_selected = ch_id in state["channel_ids"]
        prefix = "✅ " if is_selected else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{title}",
                    callback_data=f"toggle_channel:{ch_id}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="✅ Готово", callback_data="finish_channel_selection"
            )
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text="❌ Отмена", callback_data="cancel_summary_creation"
            )
        ]
    )

    selected_count = len(state["channel_ids"])
    await callback.message.edit_text(
        "📝 Создание группы сводок\n\n"
        f"Название: {state['name']}\n"
        f"Промпт: {state['prompt'][:50]}...\n\n"
        f"Шаг 3/3: Выберите каналы (выбрано: {selected_count}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("run_summary:"))
async def handle_run_summary(
    callback: CallbackQuery,
    summary_group_storage: SummaryGroupStorage,
    token_storage: TokenStorage,
) -> None:
    """Run summary generation for a group."""
    from app.config import get_settings
    from app.llm.summary_generator import SummaryGenerator
    from app.telegram.telethon_service import TelethonService

    await callback.answer("Генерирую сводку...")

    user_id = callback.from_user.id
    group_id = callback.data.split(":")[1]
    group = await summary_group_storage.get_group(group_id)

    if not group:
        await callback.message.edit_text("⚠️ Группа не найдена.")
        return

    channel_ids = group.get("channel_ids", [])
    prompt = group.get("prompt", "Создай краткую сводку")
    group_name = group.get("name", "Сводка")

    if not channel_ids:
        await callback.message.edit_text(
            f"⚠️ В группе '{group_name}' нет каналов.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✏️ Редактировать",
                            callback_data=f"edit_summary:{group_id}",
                        )
                    ]
                ]
            ),
        )
        return

    # Show progress
    await callback.message.edit_text(
        f"⏳ Генерирую сводку для '{group_name}'...\n\n"
        f"Каналов: {len(channel_ids)}\n"
        "Это может занять несколько минут."
    )

    settings = get_settings()

    # Load user's Telethon session
    session_string = await token_storage.get_telethon_session(user_id)
    telethon_service = TelethonService(settings, session_string)

    # Check Telethon configuration
    if not telethon_service.is_configured:
        await callback.message.edit_text(
            "⚠️ Telethon не настроен администратором.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="summaries_menu"
                        )
                    ]
                ]
            ),
        )
        return

    # Check user authorization
    if not session_string or not await telethon_service.is_authorized():
        await callback.message.edit_text(
            "⚠️ Требуется авторизация в Telethon.\n\n"
            "Используйте /telethon_auth для авторизации.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="summaries_menu"
                        )
                    ]
                ]
            ),
        )
        return

    try:
        # Fetch messages from all channels
        channels_data = []
        for channel_id in channel_ids:
            channel_info = await telethon_service.get_channel_info(channel_id)
            channel_name = (
                channel_info.get("title", channel_id) if channel_info else channel_id
            )

            messages_text = await telethon_service.get_channel_messages_formatted(
                channel_id, limit=500
            )

            if messages_text:
                channels_data.append(
                    {
                        "channel_name": channel_name,
                        "messages_text": messages_text,
                    }
                )

        if not channels_data:
            await callback.message.edit_text(
                "⚠️ Не удалось получить сообщения ни из одного канала.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 Назад", callback_data="summaries_menu"
                            )
                        ]
                    ]
                ),
            )
            return

        # Generate summary
        summary_generator = SummaryGenerator(settings)
        summary = await summary_generator.generate_multi_channel_summary(
            channels_data, prompt
        )

        # Send the result
        result_text = f"📊 **{group_name}**\n\n{summary}"

        # Split if too long
        if len(result_text) > 4096:
            for i in range(0, len(result_text), 4096):
                if i == 0:
                    await callback.message.edit_text(result_text[:4096])
                else:
                    await callback.message.answer(result_text[i : i + 4096])
        else:
            await callback.message.edit_text(
                result_text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔄 Обновить",
                                callback_data=f"run_summary:{group_id}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="🔙 К сводкам", callback_data="summaries_menu"
                            )
                        ],
                    ]
                ),
            )

    except Exception as e:
        logger.error(f"Summary generation error: {e}")
        await callback.message.edit_text(
            f"⚠️ Ошибка при генерации сводки:\n{str(e)[:200]}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="summaries_menu"
                        )
                    ]
                ]
            ),
        )


@router.callback_query(F.data.startswith("edit_summary:"))
async def handle_edit_summary(
    callback: CallbackQuery,
    summary_group_storage: SummaryGroupStorage,
) -> None:
    """Show edit options for a summary group."""
    await callback.answer()

    group_id = callback.data.split(":")[1]
    group = await summary_group_storage.get_group(group_id)

    if not group:
        await callback.message.edit_text("⚠️ Группа не найдена.")
        return

    name = group.get("name", "Без названия")
    prompt = group.get("prompt", "")
    channels = group.get("channel_ids", [])

    text = (
        f"✏️ Редактирование: {name}\n\n"
        f"📝 Промпт: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n\n"
        f"📺 Каналы ({len(channels)}):\n"
    )
    for ch in channels[:10]:
        text += f"  • {ch}\n"
    if len(channels) > 10:
        text += f"  ... и ещё {len(channels) - 10}\n"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="➕ Добавить канал",
                        callback_data=f"add_channel:{group_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📝 Изменить промпт",
                        callback_data=f"edit_prompt:{group_id}",
                    )
                ],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="summaries_menu")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("delete_summary:"))
async def handle_delete_summary(
    callback: CallbackQuery,
    summary_group_storage: SummaryGroupStorage,
) -> None:
    """Confirm and delete a summary group."""
    await callback.answer()

    group_id = callback.data.split(":")[1]
    group = await summary_group_storage.get_group(group_id)

    if not group:
        await callback.message.edit_text("⚠️ Группа не найдена.")
        return

    name = group.get("name", "Без названия")

    await callback.message.edit_text(
        f"🗑 Удалить группу '{name}'?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да, удалить",
                        callback_data=f"confirm_delete_summary:{group_id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Отмена", callback_data="summaries_menu"
                    ),
                ]
            ]
        ),
    )


@router.callback_query(F.data.startswith("confirm_delete_summary:"))
async def handle_confirm_delete_summary(
    callback: CallbackQuery,
    summary_group_storage: SummaryGroupStorage,
    token_storage: TokenStorage,
) -> None:
    """Actually delete the summary group."""
    await callback.answer("Удалено")

    group_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    deleted = await summary_group_storage.delete_group(group_id)

    if deleted:
        await show_summaries_menu(
            callback.message, user_id, summary_group_storage, token_storage, edit=True
        )
    else:
        await callback.message.edit_text("⚠️ Не удалось удалить группу.")


# Handler for text input during summary creation
async def process_summary_creation_input(
    message: Message,
    summary_group_storage: SummaryGroupStorage,
) -> bool:
    """
    Process text input during summary creation.

    Returns True if the message was handled, False otherwise.
    """
    user_id = message.from_user.id if message.from_user else 0
    state = _summary_creation_state.get(user_id)

    if not state:
        return False

    text = message.text.strip() if message.text else ""

    if state["step"] == "name":
        # Validate name
        if len(text) < 1 or len(text) > 50:
            await message.answer(
                "⚠️ Название должно быть от 1 до 50 символов. Попробуйте снова:"
            )
            return True

        state["name"] = text
        state["step"] = "prompt"

        await message.answer(
            "📝 Создание группы сводок\n\n"
            f"Название: {text}\n\n"
            "Шаг 2/3: Введите промпт для AI (что именно нужно извлечь из каналов):\n\n"
            "Примеры:\n"
            "• Сделай краткую сводку новостей за последние 24 часа\n"
            "• Выдели ключевые темы и тренды\n"
            "• Найди упоминания криптовалют и их анализ",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Отмена", callback_data="cancel_summary_creation"
                        )
                    ]
                ]
            ),
        )
        return True

    elif state["step"] == "prompt":
        if len(text) < 5:
            await message.answer(
                "⚠️ Промпт слишком короткий. Опишите подробнее, что нужно извлечь:"
            )
            return True

        state["prompt"] = text
        state["step"] = "channels"
        state["available_channels"] = []  # Will be loaded

        # Load user's channels from Telethon
        from app.config import get_settings
        from app.telegram.telethon_service import TelethonService

        settings = get_settings()
        session_string = await summary_group_storage.redis.get(
            f"telethon_session:{user_id}"
        )
        if session_string:
            session_string = (
                session_string.decode()
                if isinstance(session_string, bytes)
                else session_string
            )

        if not session_string:
            await message.answer(
                "⚠️ Требуется авторизация Telethon для загрузки каналов.\n"
                "Используйте /telethon_auth и повторите создание группы.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 Назад", callback_data="summaries_menu"
                            )
                        ]
                    ]
                ),
            )
            if user_id in _summary_creation_state:
                del _summary_creation_state[user_id]
            return True

        telethon_service = TelethonService(settings, session_string)
        channels = await telethon_service.get_user_channels()
        await telethon_service.disconnect()

        if not channels:
            await message.answer(
                "⚠️ Не найдено каналов. Убедитесь, что вы подписаны на каналы.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 Назад", callback_data="summaries_menu"
                            )
                        ]
                    ]
                ),
            )
            if user_id in _summary_creation_state:
                del _summary_creation_state[user_id]
            return True

        state["available_channels"] = channels

        # Build channel selection buttons
        buttons = []
        for ch in channels[:30]:  # Limit to 30 channels
            ch_id = ch.get("username") or str(ch.get("id"))
            title = ch.get("title", "Unknown")[:25]
            is_selected = ch_id in state["channel_ids"]
            prefix = "✅ " if is_selected else ""
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{prefix}{title}",
                        callback_data=f"toggle_channel:{ch_id}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Готово", callback_data="finish_channel_selection"
                )
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data="cancel_summary_creation"
                )
            ]
        )

        await message.answer(
            "📝 Создание группы сводок\n\n"
            f"Название: {state['name']}\n"
            f"Промпт: {text[:50]}...\n\n"
            "Шаг 3/3: Выберите каналы:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        return True

    elif state["step"] == "channels":
        # Channels are now selected via buttons, ignore text input
        await message.answer(
            "📌 Выберите каналы, нажимая на кнопки выше.\n"
            "Нажмите 'Готово' когда закончите."
        )
        return True

    return False


# ==================== COMPLETED TASKS SUMMARY ====================


# Temporary storage for completed tasks (to use in delete handler)
_completed_tasks_cache: dict[int, list[dict]] = {}


@router.callback_query(F.data == "completed_tasks_summary")
async def handle_completed_tasks_summary(
    callback: CallbackQuery,
    token_storage: TokenStorage,
) -> None:
    """Generate summary for completed tasks and save to Notion."""
    from app.config import get_settings
    from app.google.auth import GoogleAuthService
    from app.google.tasks import TasksService
    from app.llm.summary_generator import SummaryGenerator
    from app.notion.service import NotionService

    await callback.answer("Загружаю выполненные задачи...")

    user_id = callback.from_user.id
    settings = get_settings()

    # Check Google auth
    auth_service = GoogleAuthService(settings, token_storage)
    credentials = await auth_service.get_credentials(user_id)

    if not credentials:
        await callback.message.edit_text(
            "⚠️ Требуется авторизация в Google.\nВыполните /auth",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="summaries_menu"
                        )
                    ]
                ]
            ),
        )
        return

    # Show progress
    await callback.message.edit_text("⏳ Получаю выполненные задачи...")

    try:
        # Get completed tasks
        tasks_service = TasksService()
        tasks = await tasks_service.list_tasks(
            credentials=credentials,
            max_results=100,
            show_completed=True,
        )

        # Filter only completed
        completed_tasks = [t for t in tasks if t.get("status") == "completed"]

        if not completed_tasks:
            await callback.message.edit_text(
                "📋 Нет выполненных задач для создания сводки.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 Назад", callback_data="summaries_menu"
                            )
                        ]
                    ]
                ),
            )
            return

        # Cache for delete handler
        _completed_tasks_cache[user_id] = completed_tasks

        # Format tasks for AI
        tasks_text = "\n".join(
            [
                f"- {t.get('title', 'Без названия')}"
                + (f" ({t.get('notes', '')[:50]})" if t.get("notes") else "")
                for t in completed_tasks
            ]
        )

        await callback.message.edit_text(
            f"⏳ Генерирую сводку по {len(completed_tasks)} задачам..."
        )

        # Generate AI summary
        summary_generator = SummaryGenerator(settings)
        summary = await summary_generator.generate_summary(
            messages_text=f"Выполненные задачи:\n{tasks_text}",
            prompt="Создай краткую сводку выполненных задач. Сгруппируй по категориям, выдели ключевые достижения.",
            channel_name="Completed Tasks",
        )

        # Save to Notion if user has configured it
        notion_saved = False
        notion_url = None

        # Get user's personal Notion token
        user_notion_token = await token_storage.get_notion_token(user_id)
        parent_page_id = await token_storage.get_notion_parent_page_id(user_id)

        if user_notion_token and parent_page_id:
            notion_service = NotionService(user_notion_token, parent_page_id)

            try:
                # Find or create unified "📊 Сводки" page
                summary_page_id = await token_storage.get_notion_summary_page_id(
                    user_id
                )

                if not summary_page_id:
                    # Find or create the summary page
                    page = await notion_service.find_or_create_summary_page(
                        parent_page_id
                    )
                    summary_page_id = page["id"]
                    notion_url = page.get("url")
                    await token_storage.set_notion_summary_page_id(
                        user_id, summary_page_id
                    )

                # Append summary to the page
                await notion_service.append_summary(
                    summary_page_id, summary, summary_type="Выполненные задачи"
                )
                notion_saved = True

            except Exception as e:
                logger.warning(f"Failed to save to Notion: {e}")

        # Prepare result message
        result_text = (
            f"✅ Сводка по выполненным задачам ({len(completed_tasks)}):\n\n{summary}"
        )

        if notion_saved:
            result_text += "\n\n📝 Сохранено в Notion"
            if notion_url:
                result_text += f": {notion_url}"

        # Truncate if needed
        if len(result_text) > 3800:
            result_text = result_text[:3800] + "\n..."

        await callback.message.edit_text(
            result_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗑 Удалить выполненные",
                            callback_data="delete_completed_tasks",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔙 К сводкам", callback_data="summaries_menu"
                        )
                    ],
                ]
            ),
        )

    except Exception as e:
        logger.error(f"Completed tasks summary error: {e}")
        await callback.message.edit_text(
            f"⚠️ Ошибка: {str(e)[:200]}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="summaries_menu"
                        )
                    ]
                ]
            ),
        )


@router.callback_query(F.data == "delete_completed_tasks")
async def handle_delete_completed_tasks(
    callback: CallbackQuery,
    token_storage: TokenStorage,
) -> None:
    """Delete completed tasks (except recurring ones)."""
    from app.config import get_settings
    from app.google.auth import GoogleAuthService
    from app.google.tasks import TasksService

    await callback.answer("Удаляю задачи...")

    user_id = callback.from_user.id
    settings = get_settings()

    # Get cached tasks
    completed_tasks = _completed_tasks_cache.get(user_id, [])

    if not completed_tasks:
        await callback.message.edit_text(
            "⚠️ Список задач устарел. Сгенерируйте сводку заново.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Выполненные задачи",
                            callback_data="completed_tasks_summary",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="summaries_menu"
                        )
                    ],
                ]
            ),
        )
        return

    auth_service = GoogleAuthService(settings, token_storage)
    credentials = await auth_service.get_credentials(user_id)

    if not credentials:
        await callback.message.edit_text(
            "⚠️ Требуется авторизация.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="summaries_menu"
                        )
                    ]
                ]
            ),
        )
        return

    await callback.message.edit_text(f"⏳ Удаляю {len(completed_tasks)} задач...")

    try:
        tasks_service = TasksService()
        deleted_count = 0
        skipped_count = 0

        for task in completed_tasks:
            task_id = task.get("id")
            title = task.get("title", "")

            # Skip recurring tasks (detected by patterns in title or notes)
            is_recurring = any(
                keyword in title.lower()
                for keyword in [
                    "ежедневно",
                    "еженедельно",
                    "ежемесячно",
                    "каждый день",
                    "каждую неделю",
                    "каждый месяц",
                    "daily",
                    "weekly",
                    "monthly",
                    "recurring",
                    "повторять",
                    "повтор",
                ]
            )

            # Also check notes
            notes = task.get("notes", "") or ""
            if any(
                keyword in notes.lower() for keyword in ["recurring", "повтор", "rrule"]
            ):
                is_recurring = True

            if is_recurring:
                skipped_count += 1
                logger.info(f"Skipped recurring task: {title}")
                continue

            try:
                await tasks_service.delete_task(credentials, task_id)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete task {task_id}: {e}")

        # Clear cache
        if user_id in _completed_tasks_cache:
            del _completed_tasks_cache[user_id]

        result_text = f"✅ Удалено задач: {deleted_count}"
        if skipped_count > 0:
            result_text += f"\n⏩ Пропущено повторяющихся: {skipped_count}"

        await callback.message.edit_text(
            result_text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 К сводкам", callback_data="summaries_menu"
                        )
                    ],
                ]
            ),
        )

    except Exception as e:
        logger.error(f"Delete completed tasks error: {e}")
        await callback.message.edit_text(
            f"⚠️ Ошибка при удалении: {str(e)[:200]}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="summaries_menu"
                        )
                    ]
                ]
            ),
        )
