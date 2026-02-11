"""Main FastAPI application for core module with MCP integration."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pkg.token_storage import TokenStorage
from redis.asyncio import Redis

from core.config import Settings, get_settings
from core.handlers.http_handler import setup_routes
from core.repository.conversation_repo import ConversationRepository
from core.repository.google_auth_repo import GoogleAuthRepository
from core.repository.llm_repo import LLMRepository
from core.repository.mcp_repo import MCPRepository
from core.services.auth_service import AuthService
from core.services.chat_service import ChatService
from core.services.summary_service import SummaryService
from core.services.tool_registry import ToolRegistry
from core.services.watcher_service import WatcherService
from core.telegram.bot import create_bot, create_dispatcher
from pkg.summary_group_storage import SummaryGroupStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - initialize and cleanup resources."""
    settings = get_settings()
    logger.info("Starting application...")

    # Initialize Redis
    redis = Redis.from_url(settings.redis_url)
    await redis.ping()
    logger.info("Redis connected")

    # Initialize token storage
    token_storage = TokenStorage(redis, ttl=settings.token_ttl_seconds)

    # Repositories
    mcp_repo = MCPRepository()

    try:
        await mcp_repo.connect("google", settings.mcp_google_url)
    except Exception as e:
        logger.warning(f"Failed to connect to mcp-google: {e}")

    try:
        await mcp_repo.connect("summaries", settings.mcp_summaries_url)
    except Exception as e:
        logger.warning(f"Failed to connect to mcp-summaries: {e}")

    logger.info(f"MCP repository initialized with {len(mcp_repo.tool_names)} tools")

    conversation_repo = ConversationRepository(redis, settings.conversation_ttl_seconds)
    llm_repo = LLMRepository(settings)
    google_auth_repo = GoogleAuthRepository(settings, token_storage)

    # Services
    tool_registry = ToolRegistry(mcp_repo)
    chat_service = ChatService(llm_repo, conversation_repo, tool_registry, settings)
    auth_service = AuthService(google_auth_repo)

    # Create Telegram bot and dispatcher
    bot = await create_bot(settings)
    dp = create_dispatcher()

    watcher_service = WatcherService(bot, mcp_repo, settings, redis)

    summary_group_storage = SummaryGroupStorage(redis)
    summary_service = SummaryService(summary_group_storage, mcp_repo, bot, settings)

    # Workflow data for aiogram DI
    workflow_data = {
        "redis": redis,
        "settings": settings,
        "token_storage": token_storage,
        "chat_service": chat_service,
        "auth_service": auth_service,
        "tool_registry": tool_registry,
        "mcp_repo": mcp_repo,
        "summary_service": summary_service,
    }

    # Store in app state
    app.state.workflow_data = {**workflow_data, "bot": bot}
    app.state.bot = bot
    app.state.dp = dp

    # Start polling in background
    polling_task = asyncio.create_task(dp.start_polling(bot, **workflow_data))
    logger.info("Telegram polling started")

    # Start watcher scheduler
    scheduler_task = asyncio.create_task(watcher_service.start())
    logger.info("Watcher service started")

    # Start summary scheduler
    summary_task = asyncio.create_task(summary_service.start())
    logger.info("Summary service started")

    yield

    # Cleanup
    logger.info("Shutting down...")
    summary_task.cancel()
    try:
        await summary_task
    except asyncio.CancelledError:
        pass

    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass

    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await bot.session.close()
    await redis.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Assistant Core",
    description="Telegram bot with MCP integration",
    lifespan=lifespan,
)

setup_routes(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("core.main:app", host="0.0.0.0", port=8000, reload=True)
