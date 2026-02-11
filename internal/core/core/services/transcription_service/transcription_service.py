"""Audio transcription service using Groq Whisper API."""

import logging
import os
import tempfile
from pathlib import Path

from core.config import Settings

_langfuse_host = os.getenv("LANGFUSE_HOST", "")
if _langfuse_host:
    from langfuse.openai import AsyncOpenAI
else:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Service for transcribing audio using Groq Whisper API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )

    async def transcribe(self, audio_data: bytes, filename: str = "audio.ogg") -> str:
        """Transcribe audio data to text."""
        suffix = Path(filename).suffix or ".ogg"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_path = temp_file.name

        try:
            with open(temp_path, "rb") as audio_file:
                transcription = await self.client.audio.transcriptions.create(
                    model="whisper-large-v3-turbo",
                    file=audio_file,
                    language="ru",
                )

            text = transcription.text.strip()
            logger.info(f"Transcribed audio: {text[:50]}...")
            return text

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise
        finally:
            Path(temp_path).unlink(missing_ok=True)
