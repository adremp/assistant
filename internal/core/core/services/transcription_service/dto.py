"""DTOs for transcription service."""

from dataclasses import dataclass


@dataclass
class TranscriptionResult:
    text: str
