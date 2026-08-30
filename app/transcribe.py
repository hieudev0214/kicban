from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import OPENAI_API_KEY, OPENAI_STT_MODEL


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    text: str
    language: str | None
    segments: list[Segment]


class Transcriber(Protocol):
    def transcribe(self, wav_path: Path, language: str | None) -> TranscriptionResult: ...


# Curated common language codes for the UI dropdown (Whisper/OpenAI use ISO-639-1 codes).
LANGUAGE_CHOICES = [
    ("auto", "Auto-detect"),
    ("en", "English"),
    ("vi", "Tiếng Việt"),
    ("zh", "中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("ru", "Русский"),
    ("pt", "Português"),
    ("id", "Bahasa Indonesia"),
    ("th", "ไทย"),
    ("ar", "العربية"),
    ("hi", "हिन्दी"),
]


# Only these OpenAI transcription models support response_format="verbose_json",
# which is required to get per-segment timestamps back (needed for .srt export).
# gpt-4o-transcribe / gpt-4o-mini-transcribe only support plain "json" (text only).
_VERBOSE_JSON_MODELS = {"whisper-1"}


class OpenAITranscriber:
    def transcribe(self, wav_path: Path, language: str | None) -> TranscriptionResult:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        lang = None if language in (None, "auto") else language
        supports_segments = OPENAI_STT_MODEL in _VERBOSE_JSON_MODELS

        with open(wav_path, "rb") as f:
            kwargs = {
                "model": OPENAI_STT_MODEL,
                "file": f,
                "response_format": "verbose_json" if supports_segments else "json",
            }
            if lang:
                kwargs["language"] = lang
            resp = client.audio.transcriptions.create(**kwargs)

        text = getattr(resp, "text", "").strip()
        detected_language = getattr(resp, "language", None) or lang

        segments = []
        if supports_segments:
            for s in getattr(resp, "segments", None) or []:
                segments.append(
                    Segment(
                        start=getattr(s, "start", 0.0),
                        end=getattr(s, "end", 0.0),
                        text=getattr(s, "text", "").strip(),
                    )
                )
        if not segments and text:
            # No timestamp info from this model: treat the whole transcript as one segment.
            segments = [Segment(start=0.0, end=0.0, text=text)]
        return TranscriptionResult(text=text, language=detected_language, segments=segments)


def get_transcriber() -> Transcriber:
    return OpenAITranscriber()
