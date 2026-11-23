import re
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


# Phrases Whisper is known to hallucinate on music / silence / non-speech audio,
# because they appear verbatim in its training data (YouTube outro credits).
# Matched case-insensitively; matching segments/sentences are dropped.
_HALLUCINATION_PATTERNS = [
    r"ghiền\s*mì\s*gõ",
    r"subscribe\s+cho\s+kênh",
    r"đăng\s+ký\s+(cho\s+)?kênh",
    r"để\s+không\s+bỏ\s+lỡ\s+những\s+video\s+hấp\s+dẫn",
    r"cảm\s+ơn\s+các\s+bạn\s+đã\s+(theo\s+dõi|xem)",
    r"la\s+la\s+school",
    r"thanks?\s+(you\s+)?for\s+watching",
    r"please\s+subscribe",
    r"like\s+and\s+subscribe",
    r"subtitles?\s+by\s+the\s+amara",
    r"amara\.org",
    r"ご視聴ありがとうございました",
    r"字幕由.*提供",
    r"请不吝点赞",
]
_HALLUCINATION_RE = re.compile("|".join(_HALLUCINATION_PATTERNS), re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")

# Per-segment quality signals returned by whisper-1 verbose_json. Segments that
# are probably non-speech, or highly repetitive, are Whisper making text up.
_NO_SPEECH_PROB_MAX = 0.6
_AVG_LOGPROB_MIN = -1.0
_COMPRESSION_RATIO_MAX = 2.4


def _normalize(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def _strip_hallucinated_sentences(text: str) -> str:
    """Remove hallucinated sentences and consecutive repeats from a block of
    text (used when there are no per-segment boundaries)."""
    kept: list[str] = []
    for part in _SENTENCE_SPLIT_RE.split(text):
        if not part.strip() or _HALLUCINATION_RE.search(part):
            continue
        if kept and _normalize(kept[-1]) == _normalize(part):
            continue
        kept.append(part.strip())
    return " ".join(kept).strip()


def _is_unreliable(s) -> bool:
    no_speech = getattr(s, "no_speech_prob", None)
    avg_logprob = getattr(s, "avg_logprob", None)
    compression = getattr(s, "compression_ratio", None)
    if compression is not None and compression > _COMPRESSION_RATIO_MAX:
        return True
    # Same rule Whisper itself uses: silence-like AND low confidence.
    if (
        no_speech is not None
        and avg_logprob is not None
        and no_speech > _NO_SPEECH_PROB_MAX
        and avg_logprob < _AVG_LOGPROB_MIN
    ):
        return True
    return False


def clean_segments(segments: list[Segment]) -> list[Segment]:
    """Drop known hallucination phrases and collapse runs of repeated segments
    (Whisper's classic failure mode: one line looped over and over)."""
    cleaned: list[Segment] = []
    for seg in segments:
        text = seg.text.strip()
        if not text or _HALLUCINATION_RE.search(text):
            continue
        if cleaned and _normalize(cleaned[-1].text) == _normalize(text):
            cleaned[-1].end = max(cleaned[-1].end, seg.end)
            continue
        cleaned.append(Segment(start=seg.start, end=seg.end, text=text))
    return cleaned


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
                if _is_unreliable(s):
                    continue
                segments.append(
                    Segment(
                        start=getattr(s, "start", 0.0),
                        end=getattr(s, "end", 0.0),
                        text=getattr(s, "text", "").strip(),
                    )
                )
        if supports_segments:
            segments = clean_segments(segments)
            text = " ".join(seg.text for seg in segments).strip()
        else:
            text = _strip_hallucinated_sentences(text)
        if not segments and text:
            # No timestamp info from this model: treat the whole transcript as one segment.
            segments = [Segment(start=0.0, end=0.0, text=text)]
        return TranscriptionResult(text=text, language=detected_language, segments=segments)


def get_transcriber() -> Transcriber:
    return OpenAITranscriber()
