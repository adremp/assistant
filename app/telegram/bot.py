"""Telegram bot and dispatcher setup."""

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import Settings

logger = logging.getLogger(__name__)


async def create_bot(settings: Settings) -> Bot:
    """
    Create and configure Telegram bot.

    Args:
        settings: Application settings

    Returns:
        Configured Bot instance
    """
    bot = Bot(
        token=settings.telegram_bot_token,
    )
    logger.info("Telegram bot created")
    return bot


def create_dispatcher() -> Dispatcher:
    """
    Create and configure dispatcher with routers.

    Returns:
        Configured Dispatcher instance
    """
    from app.telegram.handlers import router
    from app.telegram.middleware import LoggingMiddleware

    dp = Dispatcher()
    dp.include_router(router)
    
    # Add middleware
    dp.message.middleware(LoggingMiddleware())
    
    logger.info("Dispatcher created with handlers")
    return dp
