"""Main FastAPI application for core module with MCP integration."""

import logging
from contextlib import asynccontextmanager

from aiogram import Bot
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pkg.token_storage import TokenStorage
from redis.asyncio import Redis

from core.config import Settings, get_settings
from core.llm.client import LLMClient
from core.mcp_client.manager import HybridToolRegistry, MCPClientManager
from core.telegram.bot import create_bot, create_dispatcher

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

    # Initialize MCP client manager and connect to servers
    mcp_manager = MCPClientManager()

    # Connect to MCP servers (graceful degradation if unavailable)
    try:
        await mcp_manager.connect("google", settings.mcp_google_url)
    except Exception as e:
        logger.warning(f"Failed to connect to mcp-google: {e}")

    try:
        await mcp_manager.connect("summaries", settings.mcp_summaries_url)
    except Exception as e:
        logger.warning(f"Failed to connect to mcp-summaries: {e}")

    logger.info(f"MCP client initialized with {len(mcp_manager.tool_names)} tools")

    # Initialize hybrid tool registry (local tools + MCP tools)
    tool_registry = HybridToolRegistry(mcp_manager)

    # Initialize LLM client
    llm_client = LLMClient(settings, redis, tool_registry)
    logger.info("LLM client initialized")

    # Create Telegram bot and dispatcher
    bot = await create_bot(settings)
    dp = create_dispatcher()

    # Workflow data for dependency injection (without bot - passed separately)
    workflow_data = {
        "redis": redis,
        "settings": settings,
        "token_storage": token_storage,
        "llm_client": llm_client,
        "tool_registry": tool_registry,
        "mcp_manager": mcp_manager,
    }

    # Store in app state (include bot here for OAuth callback)
    app.state.workflow_data = {**workflow_data, "bot": bot}
    app.state.bot = bot
    app.state.dp = dp

    # Start polling in background
    import asyncio

    polling_task = asyncio.create_task(dp.start_polling(bot, **workflow_data))
    logger.info("Telegram polling started")

    # Start watcher scheduler
    from core.scheduler.watcher_scheduler import WatcherScheduler

    scheduler = WatcherScheduler(bot, mcp_manager, settings, redis)
    scheduler_task = asyncio.create_task(scheduler.start())
    logger.info("Watcher scheduler started")

    yield

    # Cleanup
    logger.info("Shutting down...")
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/oauth/callback")
async def oauth_callback(request: Request, code: str, state: str):
    """Handle Google OAuth callback."""
    from core.google.auth import GoogleAuthService

    settings: Settings = request.app.state.workflow_data["settings"]
    token_storage: TokenStorage = request.app.state.workflow_data["token_storage"]
    bot: Bot = request.app.state.bot

    auth_service = GoogleAuthService(settings, token_storage)

    try:
        # Exchange code for tokens
        success = await auth_service.handle_callback(code, state)

        if success:
            # Parse user_id from state
            user_id = int(state)

            # Send confirmation to user
            await bot.send_message(
                user_id,
                "✅ Авторизация прошла успешно! Теперь вы можете использовать Google Calendar и Tasks.",
            )

            return HTMLResponse(
                content="""
                <html>
                <head><title>Авторизация</title></head>
                <body style="font-family: sans-serif; text-align: center; margin-top: 50px;">
                    <h1>✅ Успешно!</h1>
                    <p>Авторизация завершена. Вернитесь в Telegram.</p>
                </body>
                </html>
                """,
                status_code=200,
            )
        else:
            return HTMLResponse(
                content="<h1>Ошибка авторизации</h1>",
                status_code=400,
            )

    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return HTMLResponse(
            content=f"<h1>Ошибка</h1><p>{str(e)}</p>",
            status_code=500,
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("core.main:app", host="0.0.0.0", port=8000, reload=True)
