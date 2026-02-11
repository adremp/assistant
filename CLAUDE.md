# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

Package manager: **uv** (Python 3.13)

```bash
uv sync                    # Install dependencies from lock file
docker compose up -d       # Start all services (core + MCP + Redis)
docker compose up -d assistant-redis  # Start Redis only (for local dev)
```

Run core service locally (requires Redis):

```bash
cd internal/core && uv run uvicorn core.main:app --host 0.0.0.0 --port 8000 --reload
```

Run MCP services locally:

```bash
cd internal/mcp/google && uv run python -m mcp_google.server
cd internal/mcp/summaries && uv run python -m mcp_summaries.server
```

Quality checks (note: `justfile` paths reference old `app/` structure, use these instead):

```bash
uv run mypy internal/core/core/          # Type checking
uv run ruff format internal/             # Format
uv run ruff check internal/              # Lint
uv run pytest tests/ -v                  # Tests
```

## Architecture

Telegram bot with MCP microservices. Three deployable services communicating over HTTP:

```
┌─────────────────────────────────────────────────┐
│  assistant-core (FastAPI + aiogram)              │
│  ├── handlers/ (HTTP routes + Telegram handlers) │
│  ├── services/ (business logic)                  │
│  └── repository/ (data access)                   │
├────────────┬────────────────────────────────────┤
│            │ Streamable HTTP (MCP protocol)       │
│  ┌─────────▼──────┐  ┌──────────▼────────────┐  │
│  │  mcp-google     │  │  mcp-summaries        │  │
│  │  Calendar/Tasks │  │  Telethon/Watchers    │  │
│  └────────────────┘  └───────────────────────┘  │
├─────────────────────────────────────────────────┤
│  Redis (conversations, OAuth tokens, watchers)   │
└─────────────────────────────────────────────────┘
```

### Core Service (`internal/core/core/`)

Clean architecture with layered decomposition:

- **`main.py`** — FastAPI app entry point. Lifespan initializes Redis, repositories, services, bot, and starts Telegram polling + watcher scheduler as background tasks.
- **`handlers/telegram_handler/`** — aiogram message/callback handlers. Thin delegation to services. DI via aiogram workflow data.
- **`handlers/http_handler/`** — FastAPI routes: health check (`/health`), OAuth callback (`/oauth/callback`).
- **`services/chat_service/`** — LLM orchestration with recursive tool-calling loop. Calls LLM → processes tool_calls → calls tools via ToolRegistry → feeds results back to LLM → repeats until final response.
- **`services/tool_registry/`** — Aggregates local tools + MCP tools into OpenAI-compatible format. Injects `user_id` into MCP tool calls.
- **`services/watcher_service/`** — Background scheduler polling Telegram channels via MCP, filtering with LLM (batched for TPM limits).
- **`services/auth_service/`** — Google OAuth2 flow orchestration.
- **`services/transcription_service/`** — Voice message → text via OpenAI Whisper.
- **`repository/llm_repo/`** — OpenAI-compatible API client with exponential backoff + rate limit retry.
- **`repository/mcp_repo/`** — Manages Streamable HTTP connections to MCP servers.
- **`repository/conversation_repo/`** — Redis-backed conversation history (max 50 messages, 24h TTL).
- **`repository/google_auth_repo/`** — OAuth2 credential management.

### MCP Services

- **`internal/mcp/google/`** — FastMCP server exposing Google Calendar & Tasks tools. Each tool receives `user_id`, loads credentials from Redis via `pkg.token_storage`.
- **`internal/mcp/summaries/`** — FastMCP server for Telethon auth, channel message fetching, summary generation, and watcher CRUD.

### Shared Package (`pkg/`)

- **`token_storage.py`** — Redis-based OAuth token + timezone + Telethon session storage (used by both core and MCP services).
- **`watcher_storage.py`** — Redis-based watcher CRUD (used by core and mcp-summaries).
- **`redis_client.py`** — Redis connection utilities.

## Key Patterns

- **All state in Redis** — No database. Conversations, OAuth tokens, watchers, Telethon sessions stored in Redis with TTLs.
- **Each handler/service/repository module** has its own `dto.py` for data transfer objects.
- **MCP tools auto-inject `user_id`** — ToolRegistry adds `user_id` to every MCP tool call so services can look up per-user credentials.
- **`respond_to_user`** — Special local tool the LLM calls to produce its final answer (not an MCP tool).
- **Configuration via pydantic-settings** — Each service has a `config.py` using `Settings(BaseSettings)` loaded from env vars.
- **User-facing messages are in Russian.**
