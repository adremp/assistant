"""LLM client for Grok/OpenAI-compatible APIs with tool calling."""

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from redis.asyncio import Redis

from app.config import Settings
from app.llm.history import ConversationHistory
from app.llm.retry import RetryHandler
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — ассистент для управления календарём и задачами Google.

Возможности:
- Показывать события из Google Calendar
- Создавать события в календаре  
- Показывать задачи из Google Tasks
- Создавать задачи
- Отмечать задачи выполненными

ВАЖНО - ПРАВИЛА ОТВЕТА:
1. ВСЕГДА используй инструмент respond_to_user для ответа пользователю
2. НЕ отвечай напрямую текстом - только через respond_to_user
3. Сначала выполни нужные действия (получи задачи, создай событие и т.д.)
4. Затем вызови respond_to_user с финальным сообщением

ВАЖНО - ЧАСОВОЙ ПОЯС:
- При создании событий ВСЕГДА используй часовой пояс из контекста сообщения
- Формат времени: 2024-12-29T15:00:00+XX:XX (обязательно добавь часовой пояс!)

Правила форматирования сообщений:
- Пиши на русском языке
- Будь кратким
- Для списков используй дефис: - пункт
- Эмодзи разрешены"""


class LLMClient:
    """Async client for LLM API with tool calling support."""

    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        tool_registry: ToolRegistry,
    ):
        """
        Initialize LLM client.

        Args:
            settings: Application settings
            redis: Redis client
            tool_registry: Tool registry for tool calling
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
    ) -> str:
        """
        Send a message and get a response, handling tool calls.

        Args:
            user_id: Telegram user ID
            message: User message
            include_datetime: Whether to include current datetime in message

        Returns:
            Assistant response text
        """
        # Add current datetime context with timezone
        if include_datetime:
            from datetime import datetime
            now = datetime.now().astimezone()  # Get local timezone automatically
            tz_offset = now.strftime("%z")  # e.g., "+0500"
            tz_formatted = f"{tz_offset[:3]}:{tz_offset[3:]}"  # e.g., "+05:00"
            now_str = now.strftime("%Y-%m-%d %H:%M:%S %z")
            message = f"[Текущее время: {now_str}, часовой пояс: {tz_formatted}]\n\n{message}"

        # Get conversation history
        history = await self.history.get(user_id)

        # Ensure system message is set
        if not history or history[0].get("role") != "system":
            await self.history.set_system_message(user_id, SYSTEM_PROMPT)
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
            # Full message for API (needs all details)
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
            
            # Compact message for Redis (save tokens)
            tool_names = [tc.function.name for tc in message.tool_calls]
            assistant_message_compact = {
                "role": "assistant",
                "content": f"[Использованы инструменты: {', '.join(tool_names)}]",
            }
            await self.history.append(user_id, assistant_message_compact)

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
                    
                    # Special handling for respond_to_user tool
                    if tool_name == "respond_to_user" and result.get("type") == "user_response":
                        user_response = result.get("response", "")
                        # Save to history and return directly
                        await self.history.append(user_id, {"role": "assistant", "content": user_response})
                        return user_response
                    
                    result_str = json.dumps(result, ensure_ascii=False)
                except Exception as e:
                    logger.error(f"Tool {tool_name} failed: {e}")
                    result_str = json.dumps({
                        "success": False,
                        "error": str(e),
                    }, ensure_ascii=False)

                # Add tool result to current history for API (not saved to Redis)
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                }
                history.append(tool_message)

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
