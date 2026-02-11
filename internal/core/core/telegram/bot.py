"""Telegram bot and dispatcher setup."""

import logging

from aiogram import Bot, Dispatcher

from core.config import Settings

logger = logging.getLogger(__name__)


async def create_bot(settings: Settings) -> Bot:
    """Create and configure Telegram bot."""
    bot = Bot(
        token=settings.telegram_bot_token,
    )
    logger.info("Telegram bot created")
    return bot


def create_dispatcher() -> Dispatcher:
    """Create and configure dispatcher with routers."""
    from core.handlers.telegram_handler import router
    from core.handlers.telegram_handler.summary_handler import summary_router
    from core.telegram.middleware import LoggingMiddleware

    dp = Dispatcher()
    dp.include_router(summary_router)
    dp.include_router(router)

    dp.message.middleware(LoggingMiddleware())

    logger.info("Dispatcher created with handlers")
    return dp
