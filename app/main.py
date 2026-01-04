"""FastAPI application with Telegram bot integration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.config import get_settings
from app.storage.tokens import TokenStorage
from app.storage.reminders import ReminderStorage
from app.storage.pending_responses import PendingResponseStorage
from app.scheduler.service import ReminderScheduler
from app.llm.client import LLMClient
from app.llm.history import ConversationHistory
from app.tools.registry import init_tool_registry
from app.telegram.bot import create_bot, create_dispatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Initializes and cleans up resources:
    - Redis connection
    - Telegram bot
    - LLM client
    - Reminder scheduler
    """
    settings = get_settings()
    logger.info("Starting application...")

    # Initialize Redis
    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.ping()
        logger.info("Connected to Redis")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise

    # Initialize token storage
    token_storage = TokenStorage(redis, settings.token_ttl_seconds)

    # Initialize Telegram bot first (needed for scheduler)
    bot = await create_bot(settings)
    dp = create_dispatcher()

    # Initialize reminder storages and scheduler
    reminder_storage = ReminderStorage(redis)
    pending_storage = PendingResponseStorage(redis)
    
    reminder_scheduler = ReminderScheduler(
        redis_url=settings.redis_url,
        bot=bot,
        reminder_storage=reminder_storage,
        pending_storage=pending_storage,
        token_storage=token_storage,
    )
    await reminder_scheduler.start()
    logger.info("Reminder scheduler started")

    # Initialize tool registry with scheduler and storage
    tool_registry = init_tool_registry(redis, token_storage, reminder_scheduler, reminder_storage)
    logger.info(f"Loaded tools: {tool_registry.tool_names}")

    # Initialize LLM client
    llm_client = LLMClient(
        settings=settings,
        redis=redis,
        tool_registry=tool_registry,
    )
    logger.info(f"LLM client initialized (model: {settings.llm_model})")

    # Initialize summarization worker
    from app.llm.summarization_worker import SummarizationWorker
    summarization_worker = SummarizationWorker(redis, llm_client)
    await summarization_worker.start()
    
    # Store dependencies in dispatcher's workflow_data for handlers to access
    dp.workflow_data["redis"] = redis
    dp.workflow_data["token_storage"] = token_storage
    dp.workflow_data["llm_client"] = llm_client
    dp.workflow_data["tool_registry"] = tool_registry
    dp.workflow_data["reminder_scheduler"] = reminder_scheduler
    dp.workflow_data["pending_storage"] = pending_storage

    # Store in app state
    app.state.redis = redis
    app.state.bot = bot
    app.state.dp = dp
    app.state.llm_client = llm_client
    app.state.summarization_worker = summarization_worker
    app.state.reminder_scheduler = reminder_scheduler

    logger.info("Application started successfully")

    # Start polling in background
    import asyncio
    polling_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("Telegram bot polling started")

    yield

    # Cleanup
    logger.info("Shutting down application...")
    
    # Stop reminder scheduler
    await reminder_scheduler.stop()
    
    # Stop summarization worker
    await summarization_worker.stop()
    
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await bot.session.close()
    await redis.close()
    
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Assistant Bot",
    description="Telegram bot with Google Calendar/Tasks and LLM integration",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Assistant Bot",
        "version": "0.1.0",
        "status": "running",
    }
