"""LLM client for Grok/OpenAI-compatible APIs with tool calling."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from pkg.timezone import to_tzinfo
from redis.asyncio import Redis

from core.config import Settings
from core.llm.history import ConversationHistory
from core.llm.retry import RetryHandler
from core.mcp_client.manager import HybridToolRegistry

# Use Langfuse-wrapped client only if properly configured
_langfuse_host = os.getenv("LANGFUSE_HOST", "")
if _langfuse_host:
    from langfuse.openai import AsyncOpenAI
else:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are an assistant for managing Google Calendar, Tasks, and Telegram summaries.

Capabilities:
- Show events from Google Calendar
- Create calendar events
- Update calendar events
- Show tasks from Google Tasks
- Create tasks
- Update tasks
- Mark tasks as completed
- Authenticate Telethon (MTProto) for Telegram channel access
- Create and manage summary groups for Telegram channels
- Generate AI-powered summaries from channel messages
- Create watchers for automatic Telegram chat monitoring by prompt
- List and delete watchers

IMPORTANT - RESPONSE RULES:
1. ALWAYS use the respond_to_user tool to reply to the user
2. DO NOT respond with plain text - only through respond_to_user
3. First perform necessary actions (get tasks, create event, etc.)
4. Then call respond_to_user with the final message

IMPORTANT - TIMEZONE:
- Current user timezone: {user_timezone}
- Interpret any user-provided time (\"завтра в 10\", \"в пятницу\", \"через 2 часа\") strictly in the user's timezone. Never assume server timezone.
- Store/submit times in ISO 8601 with offset: 2024-12-29T15:00:00+07:00 (offset required). Convert recurring events using the same timezone (with DST rules).
- In replies include both local time with TZ and UTC conversion, e.g.: \"10:00 2024-05-10 Europe/Moscow (UTC+03:00 -> 07:00Z)\".
- If the parsed local time is in the past relative to the user's \"now\", ask for clarification or propose the nearest future time.
- Resolve ambiguous inputs: if only time is given, ask for date; if date without year, use the nearest future date and say which one.

IMPORTANT - TELETHON AUTHENTICATION:
- If user wants to use Telegram summaries, they need to authorize with telethon_auth_start(phone)
- Phone must be in international format: +79001234567
- After code is sent, WARN the user: send the code with dashes or spaces (e.g. 1-2-3-4-5) to avoid Telegram blocking the login for "sharing the code"
- When receiving code from user, strip all non-digit characters before passing to telethon_auth_submit_code(code)

IMPORTANT - COMPLETED TASKS:
- If user mentions completing a task that doesn't exist in their task list, create it with today's date and immediately mark it as completed
- This helps track completed work that wasn't previously added as a task

LANGUAGE RULE:
- ALWAYS respond in Russian language regardless of the instruction language
- All user-facing messages must be in Russian

Message formatting rules:
- Be concise
- Use dash for lists: - item
- Emojis are allowed
- Markdown is strictly prohibited"""


class LLMClient:
    """Async client for LLM API with tool calling support."""

    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        tool_registry: HybridToolRegistry,
    ):
        """
        Initialize LLM client.

        Args:
            settings: Application settings
            redis: Redis client
            tool_registry: Hybrid tool registry (local + MCP tools)
        """
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
        self.history = ConversationHistory(redis, settings.conversation_ttl_seconds)
        self.retry_handler = RetryHandler(
            max_retries=settings.llm_max_retries,
        )
        self.tool_registry = tool_registry

    async def chat(
        self,
        user_id: int,
        message: str,
        include_datetime: bool = True,
        user_timezone: str | None = None,
    ) -> str:
        """
        Send a message and get a response, handling tool calls.

        Args:
            user_id: Telegram user ID
            message: User message
            include_datetime: Whether to include current datetime in message
            user_timezone: Optional user timezone (IANA or offset) to inject into system prompt and context

        Returns:
            Assistant response text
        """
        tz_name = user_timezone or "unknown"
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(user_timezone=tz_name)

        # Add current datetime context with timezone
        if include_datetime:
            tzinfo = to_tzinfo(tz_name)
            if tzinfo is None:
                logger.warning(
                    f"Invalid timezone provided: {tz_name}, using UTC fallback"
                )
            if tzinfo:
                now = datetime.now(tzinfo).astimezone(tzinfo)
            else:
                now = datetime.now(timezone.utc)
            tz_offset = now.strftime("%z")  # e.g., "+0500"
            tz_formatted = f"{tz_offset[:3]}:{tz_offset[3:]}"  # e.g., "+05:00"
            now_str = now.strftime("%Y-%m-%d %H:%M:%S %z")
            message = (
                f"[Текущее время: {now_str}, часовой пояс: {tz_formatted}]\n\n{message}"
            )

        # Get conversation history
        history = await self.history.get(user_id)

        # Ensure system message is set
        if (
            not history
            or history[0].get("role") != "system"
            or history[0].get("content") != system_prompt
        ):
            await self.history.set_system_message(user_id, system_prompt)
            history = await self.history.get(user_id)

        # Add user message
        await self.history.append(user_id, {"role": "user", "content": message})
        history.append({"role": "user", "content": message})

        # Get tools
        tools = self.tool_registry.get_all_tools()

        # Call LLM with retry
        response = await self._call_llm(history, tools)

        # Process response (may include tool calls)
        final_response = await self._process_response(
            user_id=user_id,
            response=response,
            history=history,
            tools=tools,
        )

        return final_response

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        """
        Call LLM API with retry logic.

        Args:
            messages: Conversation messages
            tools: Available tools

        Returns:
            API response
        """

        async def make_request():
            return await self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                tools=tools if tools else None,
                temperature=self.settings.llm_temperature,
            )

        return await self.retry_handler.execute(make_request)

    async def _process_response(
        self,
        user_id: int,
        response: Any,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        depth: int = 0,
    ) -> str:
        """
        Process LLM response, handling tool calls recursively.

        Args:
            user_id: Telegram user ID
            response: LLM API response
            history: Current conversation history
            tools: Available tools
            depth: Recursion depth (max 5)

        Returns:
            Final assistant response text
        """
        if depth > 5:
            logger.warning(f"Max tool call depth reached for user {user_id}")
            return "Извините, произошла ошибка при обработке запроса."

        message = response.choices[0].message

        # Check for tool calls
        if message.tool_calls:
            # Full message for API and history (with all tool call details)
            assistant_message_full = {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
            history.append(assistant_message_full)
            # Save full message to Redis
            await self.history.append(user_id, assistant_message_full)

            # Execute each tool call
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                logger.info(f"Executing tool {tool_name} for user {user_id}")

                try:
                    result = await self.tool_registry.execute_tool(
                        name=tool_name,
                        user_id=user_id,
                        arguments=arguments,
                    )

                    # Handle respond_to_user tool - it returns the response directly
                    if tool_name == "respond_to_user" and isinstance(result, str):
                        # Save the actual response to history
                        await self.history.append(
                            user_id, {"role": "assistant", "content": result}
                        )
                        return result

                    # Handle MCP tool results (JSON)
                    if isinstance(result, dict):
                        # Special handling for not_authorized - return constant message without history
                        if result.get("error") == "not_authorized":
                            from core.constants import AUTH_REQUIRED_MESSAGE

                            return {
                                "type": "auth_required",
                                "message": AUTH_REQUIRED_MESSAGE,
                            }
                        result_str = json.dumps(result, ensure_ascii=False)
                    else:
                        result_str = str(result)

                except Exception as e:
                    logger.error(f"Tool {tool_name} failed: {e}")
                    result_str = json.dumps(
                        {
                            "success": False,
                            "error": str(e),
                        },
                        ensure_ascii=False,
                    )

                # Add tool result to history (both in-memory and Redis)
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                }
                history.append(tool_message)
                await self.history.append(user_id, tool_message)

            # Call LLM again with tool results
            response = await self._call_llm(history, tools)
            return await self._process_response(
                user_id=user_id,
                response=response,
                history=history,
                tools=tools,
                depth=depth + 1,
            )

        # No tool calls, return the response
        content = message.content or ""

        # Save assistant response to history
        await self.history.append(user_id, {"role": "assistant", "content": content})

        return content

    async def clear_history(self, user_id: int) -> None:
        """
        Clear conversation history for a user.

        Args:
            user_id: Telegram user ID
        """
        await self.history.clear(user_id)
        logger.info(f"Cleared conversation history for user {user_id}")
