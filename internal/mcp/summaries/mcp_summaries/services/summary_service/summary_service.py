"""Summary generator with TPM-aware chunking."""

import logging
from typing import Any

from langfuse.openai import AsyncOpenAI

from mcp_summaries.config import Settings

logger = logging.getLogger(__name__)

# Approximate chars per token (conservative estimate for Russian text)
CHARS_PER_TOKEN = 3


class SummaryService:
    """Generator for AI-powered channel summaries with TPM-aware chunking."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
        # Reserve ~20% for prompt and response
        self.max_tokens_per_chunk = int(settings.llm_tpm_limit * 0.8)
        self.max_chars_per_chunk = self.max_tokens_per_chunk * CHARS_PER_TOKEN

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // CHARS_PER_TOKEN

    def _chunk_text(self, text: str) -> list[str]:
        if len(text) <= self.max_chars_per_chunk:
            return [text]

        chunks = []
        lines = text.split("\n")
        current_chunk: list[str] = []
        current_size = 0

        for line in lines:
            line_size = len(line) + 1
            if current_size + line_size > self.max_chars_per_chunk:
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_size = line_size
            else:
                current_chunk.append(line)
                current_size += line_size

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        logger.info(f"Split text into {len(chunks)} chunks")
        return chunks

    async def _summarize_chunk(
        self,
        chunk: str,
        prompt: str,
        channel_name: str,
        is_partial: bool = False,
    ) -> str:
        if is_partial:
            system_prompt = (
                f"Ты анализируешь часть истории канала '{channel_name}'. "
                "Создай краткую сводку ключевых тем и событий из этой части. "
                "Эта сводка будет объединена с другими частями."
            )
        else:
            system_prompt = (
                f"Ты анализируешь историю канала '{channel_name}'. "
                f"Задача от пользователя: {prompt}"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"История сообщений:\n\n{chunk}"},
        ]

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                temperature=self.settings.llm_temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    async def _merge_summaries(
        self,
        summaries: list[str],
        prompt: str,
        channel_name: str,
    ) -> str:
        combined = "\n\n---\n\n".join(summaries)

        system_prompt = (
            f"Ты получил несколько частичных сводок по каналу '{channel_name}'. "
            f"Объедини их в единую связную сводку согласно задаче пользователя: {prompt}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Частичные сводки:\n\n{combined}"},
        ]

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                temperature=self.settings.llm_temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLM merge failed: {e}")
            raise

    async def generate_summary(
        self,
        messages_text: str,
        prompt: str,
        channel_name: str,
    ) -> str:
        chunks = self._chunk_text(messages_text)

        if len(chunks) == 1:
            return await self._summarize_chunk(
                chunks[0], prompt, channel_name, is_partial=False
            )

        logger.info(
            f"Multi-chunk summarization: {len(chunks)} chunks for {channel_name}"
        )

        partial_summaries = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Summarizing chunk {i + 1}/{len(chunks)}")
            summary = await self._summarize_chunk(
                chunk, prompt, channel_name, is_partial=True
            )
            partial_summaries.append(summary)

        return await self._merge_summaries(partial_summaries, prompt, channel_name)

    async def generate_multi_channel_summary(
        self,
        channels_data: list[dict[str, Any]],
        prompt: str,
    ) -> str:
        if len(channels_data) == 1:
            return await self.generate_summary(
                channels_data[0]["messages_text"],
                prompt,
                channels_data[0]["channel_name"],
            )

        channel_summaries = []
        for data in channels_data:
            channel_name = data["channel_name"]
            messages_text = data["messages_text"]

            if not messages_text:
                channel_summaries.append(f"**{channel_name}**: Нет сообщений")
                continue

            summary = await self.generate_summary(messages_text, prompt, channel_name)
            channel_summaries.append(f"**{channel_name}**:\n{summary}")

        combined = "\n\n---\n\n".join(channel_summaries)

        system_prompt = (
            "Ты получил сводки по нескольким каналам. "
            f"Создай общую сводку согласно задаче: {prompt}\n\n"
            "Если каналы связаны тематически, выдели общие темы и тренды."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Сводки по каналам:\n\n{combined}"},
        ]

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                temperature=self.settings.llm_temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Multi-channel summary failed: {e}")
            return combined
