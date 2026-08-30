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
DB_PATH = DATA_DIR / "jobs.db"
LOG_PATH = DATA_DIR / "app.log"

for d in (UPLOADS_DIR, DOWNLOADS_DIR, AUDIO_DIR, TRANSCRIPTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
OPENAI_ENABLED = bool(OPENAI_API_KEY)

MAX_DURATION_SECONDS = int(os.environ.get("MAX_DURATION_SECONDS", "7200"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_JOBS_PER_HOUR_PER_IP = int(os.environ.get("MAX_JOBS_PER_HOUR_PER_IP", "5"))

# Secret used to sign session cookies (itsdangerous). MUST be set to a long
# random value in production - the dev fallback is only safe for local use,
# since anyone with it can forge login sessions.
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or "dev-only-insecure-secret-key"
SESSION_COOKIE_NAME = "kicban_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600  # 30 days

# Emails (comma-separated) that are automatically granted the admin role the
# moment they register or log in - the only way to bootstrap the first admin
# account without directly editing the database.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# Price charged per transcription job, deducted from the user's wallet up
# front and refunded automatically if the job fails (see jobs.py).
PRICE_PER_JOB_VND = int(os.environ.get("PRICE_PER_JOB_VND", "5000"))
MIN_TOPUP_VND = int(os.environ.get("MIN_TOPUP_VND", "10000"))

# Manual bank-transfer top-up: no payment gateway account needed at all -
# the customer scans a VietQR code (a free, public QR standard, no API key
# required) pointing at this bank account, then an admin manually confirms
# the transfer arrived and credits the wallet from the admin panel. Chosen
# over VNPay/PayOS because both require identity-verified merchant
# onboarding (a legal AML requirement, not something any gateway can skip)
# that was blocking getting the app usable quickly.
BANK_ID = os.environ.get("BANK_ID", "").strip()  # VietQR bank short code or BIN, e.g. "vietcombank" or "970436"
BANK_ACCOUNT_NO = os.environ.get("BANK_ACCOUNT_NO", "").strip()
BANK_ACCOUNT_NAME = os.environ.get("BANK_ACCOUNT_NAME", "").strip()
MANUAL_TOPUP_ENABLED = bool(BANK_ID and BANK_ACCOUNT_NO and BANK_ACCOUNT_NAME)

# Paths to Netscape-format cookies.txt files for yt-dlp. Needed on hosts
# whose IP gets bot-detection blocked by YouTube/TikTok (common for
# cloud/datacenter IPs). Leave unset to run without cookies (works fine on
# residential IPs). Kept as separate files per site rather than one merged
# file: combining TikTok's and YouTube's cookies into a single cookies.txt
# was observed to break TikTok's extraction (its anti-bot challenge seems
# sensitive to unrelated cookies being present), so each site gets its own.
YTDLP_COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", "").strip() or None
YTDLP_COOKIES_FILE_YOUTUBE = (
    os.environ.get("YTDLP_COOKIES_FILE_YOUTUBE", "").strip() or None
)
