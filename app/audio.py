import json
import subprocess
from pathlib import Path


class AudioError(Exception):
    pass


class NoAudioStreamError(AudioError):
    pass


def probe(path: Path) -> dict:
    """Return {'duration': float, 'has_audio': bool} for a media file."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration:stream=codec_type",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise AudioError(f"ffprobe failed: {e.stderr.strip()}") from e

    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration_str = info.get("format", {}).get("duration")
    duration = float(duration_str) if duration_str is not None else 0.0
    return {"duration": duration, "has_audio": has_audio}


def normalize_to_wav(input_path: Path, output_path: Path) -> None:
    """Extract mono 16kHz PCM wav audio from any media file for STT input."""
    info = probe(input_path)
    if not info["has_audio"]:
        raise NoAudioStreamError("This file doesn't contain a readable audio track.")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-acodec", "pcm_s16le",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise AudioError(f"ffmpeg failed: {e.stderr.strip()}") from e
