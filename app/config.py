import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
DOWNLOADS_DIR = DATA_DIR / "downloads"
AUDIO_DIR = DATA_DIR / "audio"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
MODELS_DIR = BASE_DIR / "models"
DB_PATH = DATA_DIR / "jobs.db"
LOG_PATH = DATA_DIR / "app.log"

for d in (UPLOADS_DIR, DOWNLOADS_DIR, AUDIO_DIR, TRANSCRIPTS_DIR, MODELS_DIR):
    d.mkdir(parents=True, exist_ok=True)

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
OPENAI_ENABLED = bool(OPENAI_API_KEY)

MAX_DURATION_SECONDS = int(os.environ.get("MAX_DURATION_SECONDS", "7200"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_JOBS_PER_HOUR_PER_IP = int(os.environ.get("MAX_JOBS_PER_HOUR_PER_IP", "5"))

# Path to a Netscape-format cookies.txt for yt-dlp. Needed on hosts whose IP
# gets bot-detection blocked by YouTube/TikTok (common for cloud/datacenter
# IPs). Leave unset to run without cookies (works fine on residential IPs).
YTDLP_COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", "").strip() or None
