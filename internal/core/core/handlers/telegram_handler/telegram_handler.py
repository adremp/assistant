"""Telegram message handlers - thin layer that delegates to services."""

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from pkg.token_storage import TokenStorage

from core.repository.llm_repo import RateLimitException
from core.services.auth_service import AuthService
from core.services.chat_service import ChatService
from core.services.transcription_service import TranscriptionService

logger = logging.getLogger(__name__)

router = Router(name="main")


def get_main_keyboard() -> InlineKeyboardMarkup:
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
                    text="📊 Саммари", callback_data="sg:menu"
                )
            ],
        ]
    )


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    user = message.from_user
    user_name = user.first_name if user else "друг"

    await message.answer(
        f"👋 Привет, {user_name}!\n\n"
        "Я — твой персональный ассистент для управления календарём и задачами.\n\n"
        "Команды:\n"
        "/auth — авторизация в Google\n"
        "/tasks — задачи на сегодня\n"
        "/summaries — управление саммари-группами\n"
        "/clear — очистить историю диалога\n\n"
        "💬 Или просто напиши, что тебе нужно!",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(
        "📚 Справка\n\n"
        "Примеры запросов:\n"
        "- Покажи мои события на сегодня\n"
        "- Создай встречу завтра в 10:00\n"
        "- Какие у меня задачи?\n"
        "- Добавь задачу купить молоко\n"
        "- Авторизуй Telethon +79001234567\n\n"
        "Команды:\n"
        "/start — начать работу\n"
        "/auth — авторизация в Google\n"
        "/tasks — задачи на сегодня\n"
        "/summaries — управление саммари-группами\n"
        "/timezone — обновить часовой пояс\n"
        "/clear — очистить историю диалога"
    )


@router.message(Command("timezone"))
async def cmd_timezone(
    message: Message,
    chat_service: ChatService,
    token_storage: TokenStorage,
) -> None:
    user_id = message.from_user.id if message.from_user else 0

    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        response = await _get_chat_response_with_rate_limit_handling(
            message,
            chat_service,
            user_id,
            "Обнови мой часовой пояс из настроек Google Calendar и сохрани его.",
            token_storage,
        )
        await _send_response(message, response)
    except Exception as e:
        logger.error(f"Timezone update error: {e}")
        await message.answer("⚠️ Ошибка при обновлении часового пояса.")


@router.message(Command("tasks"))
async def handle_tasks_command(
    message: Message,
    chat_service: ChatService,
    token_storage: TokenStorage,
) -> None:
    user_id = message.from_user.id if message.from_user else 0

    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        response = await _get_chat_response_with_rate_limit_handling(
            message,
            chat_service,
            user_id,
            "Покажи мои задачи на сегодня.",
            token_storage,
        )
        await _send_response(message, response)
    except Exception as e:
        logger.error(f"Tasks command error: {e}")
        await message.answer("⚠️ Ошибка при получении задач.")


@router.callback_query(F.data == "tasks_today")
async def handle_tasks_today_callback(
    callback: CallbackQuery,
    chat_service: ChatService,
    token_storage: TokenStorage,
) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    message = callback.message

    if message and message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        response = await _get_chat_response_with_rate_limit_handling(
            message,
            chat_service,
            user_id,
            "Покажи мои задачи на сегодня.",
            token_storage,
        )
        await _send_response(message, response)
    except Exception as e:
        logger.error(f"Tasks callback error: {e}")
        await message.answer("⚠️ Ошибка при получении задач.")


@router.callback_query(F.data == "events_today")
async def handle_events_today_callback(
    callback: CallbackQuery,
    chat_service: ChatService,
    token_storage: TokenStorage,
) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    message = callback.message

    if message and message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        response = await _get_chat_response_with_rate_limit_handling(
            message,
            chat_service,
            user_id,
            "Покажи мои события на сегодня.",
            token_storage,
        )
        await _send_response(message, response)
    except Exception as e:
        logger.error(f"Events callback error: {e}")
        await message.answer("⚠️ Ошибка при получении событий.")


@router.message(Command("auth"))
async def handle_auth(message: Message, auth_service: AuthService) -> None:
    user_id = message.from_user.id if message.from_user else 0

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
async def handle_clear(message: Message, chat_service: ChatService) -> None:
    user_id = message.from_user.id if message.from_user else 0
    await chat_service.clear_history(user_id)

    await message.answer("🗑 История диалога очищена.")


@router.message(F.text)
async def handle_text_message(
    message: Message,
    chat_service: ChatService,
    token_storage: TokenStorage,
) -> None:
    if not message.text:
        return

    user_id = message.from_user.id if message.from_user else 0
    text = message.text

    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        response = await _get_chat_response_with_rate_limit_handling(
            message, chat_service, user_id, text, token_storage
        )
        await _send_response(message, response)
    except Exception as e:
        logger.error(f"LLM error for user {user_id}: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обработке запроса.\n"
            "Попробуйте ещё раз или выполните /clear для сброса диалога."
        )


async def _send_response(message: Message, response: str | dict) -> None:
    """Send response to user, handling special cases."""
    if isinstance(response, dict) and response.get("type") == "auth_required":
        await message.answer(response.get("message", ""))
        return

    if isinstance(response, str):
        if len(response) > 4096:
            for i in range(0, len(response), 4096):
                await message.answer(response[i : i + 4096])
        else:
            await message.answer(response)


async def _get_chat_response_with_rate_limit_handling(
    message: Message,
    chat_service: ChatService,
    user_id: int,
    text: str,
    token_storage: TokenStorage | None = None,
    max_retries: int = 3,
) -> str:
    """Get chat response with rate limit handling."""
    user_timezone = None
    if token_storage:
        try:
            user_timezone = await token_storage.get_user_timezone(user_id)
        except Exception as e:
            logger.warning(f"Failed to get user timezone for {user_id}: {e}")

    for attempt in range(max_retries):
        try:
            return await chat_service.process_message(user_id, text, user_timezone=user_timezone)
        except RateLimitException as e:
            if attempt < max_retries - 1:
                await message.answer(
                    f"⏳ Превышен лимит запросов. Подождите {int(e.retry_after)} секунд..."
                )
                await asyncio.sleep(e.retry_after)
                if message.bot:
                    await message.bot.send_chat_action(message.chat.id, "typing")
            else:
                raise Exception("Превышен лимит запросов. Попробуйте позже.")

    raise Exception("Не удалось получить ответ")


@router.message(F.voice)
async def handle_voice_message(
    message: Message,
    chat_service: ChatService,
    token_storage: TokenStorage,
) -> None:
    from core.config import get_settings

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

        response = await _get_chat_response_with_rate_limit_handling(
            message, chat_service, user_id, transcribed_text, token_storage
        )
        await _send_response(message, response)

    except Exception as e:
        logger.error(f"Voice message error for user {user_id}: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обработке голосового сообщения.\n"
            "Попробуйте ещё раз."
        )
