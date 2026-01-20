"""Summary generator with TPM-aware chunking."""

import logging
from typing import Any

from langfuse.openai import AsyncOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)

# Approximate chars per token (conservative estimate for Russian text)
CHARS_PER_TOKEN = 3


class SummaryGenerator:
    """Generator for AI-powered channel summaries with TPM-aware chunking."""

    def __init__(self, settings: Settings):
        """
        Initialize summary generator.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
        # Calculate max chars per chunk based on TPM limit
        # Reserve ~20% for prompt and response
        self.max_tokens_per_chunk = int(settings.llm_tpm_limit * 0.8)
        self.max_chars_per_chunk = self.max_tokens_per_chunk * CHARS_PER_TOKEN

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        return len(text) // CHARS_PER_TOKEN

    def _chunk_text(self, text: str) -> list[str]:
        """
        Split text into chunks that fit within TPM limit.

        Args:
            text: Full text to chunk

        Returns:
            List of text chunks
        """
        if len(text) <= self.max_chars_per_chunk:
            return [text]

        chunks = []
        lines = text.split("\n")
        current_chunk = []
        current_size = 0

        for line in lines:
            line_size = len(line) + 1  # +1 for newline
            
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
        """
        Summarize a single chunk of messages.

        Args:
            chunk: Messages text
            prompt: User's custom prompt
            channel_name: Name of the channel
            is_partial: Whether this is a partial summary

        Returns:
            Summary text
        """
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
        """
        Merge partial summaries into final summary.

        Args:
            summaries: List of partial summaries
            prompt: User's custom prompt
            channel_name: Name of the channel

        Returns:
            Final merged summary
        """
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
        """
        Generate summary for channel messages.

        Uses multi-step summarization for large histories:
        1. Split into TPM-aware chunks
        2. Summarize each chunk
        3. Merge partial summaries

        Args:
            messages_text: Token-optimized messages (sender: text format)
            prompt: User's custom prompt
            channel_name: Name of the channel

        Returns:
            Generated summary
        """
        chunks = self._chunk_text(messages_text)
        
        if len(chunks) == 1:
            # Single chunk - direct summarization
            logger.info(f"Single chunk summarization for {channel_name}")
            return await self._summarize_chunk(
                chunks[0], prompt, channel_name, is_partial=False
            )

        # Multi-chunk - summarize each, then merge
        logger.info(f"Multi-chunk summarization: {len(chunks)} chunks for {channel_name}")
        
        partial_summaries = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Summarizing chunk {i+1}/{len(chunks)}")
            summary = await self._summarize_chunk(
                chunk, prompt, channel_name, is_partial=True
            )
            partial_summaries.append(summary)

        # Merge all partial summaries
        return await self._merge_summaries(partial_summaries, prompt, channel_name)

    async def generate_multi_channel_summary(
        self,
        channels_data: list[dict[str, Any]],
        prompt: str,
    ) -> str:
        """
        Generate combined summary for multiple channels.

        Args:
            channels_data: List of {channel_name: str, messages_text: str}
            prompt: User's custom prompt

        Returns:
            Combined summary
        """
        if len(channels_data) == 1:
            return await self.generate_summary(
                channels_data[0]["messages_text"],
                prompt,
                channels_data[0]["channel_name"],
            )

        # Generate summary for each channel
        channel_summaries = []
        for data in channels_data:
            channel_name = data["channel_name"]
            messages_text = data["messages_text"]
            
            if not messages_text:
                channel_summaries.append(f"**{channel_name}**: Нет сообщений")
                continue

            summary = await self.generate_summary(
                messages_text, prompt, channel_name
            )
            channel_summaries.append(f"**{channel_name}**:\n{summary}")

        # Combine all channel summaries
        combined = "\n\n---\n\n".join(channel_summaries)
        
        # Generate final cross-channel summary
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
            # Return individual summaries if merge fails
            return combined
