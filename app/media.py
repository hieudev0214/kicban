import shutil
import threading
from pathlib import Path

import httpx
import yt_dlp
import yt_dlp.extractor as yt_dlp_extractor

from app.config import DATA_DIR, DOWNLOADS_DIR, MAX_DURATION_SECONDS, YTDLP_COOKIES_FILE

_RUNTIME_COOKIES_FILE = DATA_DIR / "cookies_runtime.txt"
_cookies_lock = threading.Lock()


def _writable_cookies_path() -> str | None:
    """yt-dlp rewrites the cookiefile on every close() to persist updated
    cookies. On Render, YTDLP_COOKIES_FILE points at a Secret File mount
    (/etc/secrets/...), which is read-only - that write fails and raises an
    OSError that masks the real download error (or even fails an otherwise
    successful download). Work around it by copying the configured cookies
    file to a writable path once and using that copy for yt-dlp instead."""
    if not YTDLP_COOKIES_FILE:
        return None
    with _cookies_lock:
        if not _RUNTIME_COOKIES_FILE.exists():
            shutil.copyfile(YTDLP_COOKIES_FILE, _RUNTIME_COOKIES_FILE)
    return str(_RUNTIME_COOKIES_FILE)


def _ytdlp_base_opts() -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True}
    cookies_path = _writable_cookies_path()
    if cookies_path:
        opts["cookiefile"] = cookies_path
    return opts


def _is_known_site(url: str) -> bool:
    """True if a specific (non-generic) yt-dlp extractor recognizes this URL,
    e.g. YouTube/TikTok/Facebook. Used to decide whether a yt-dlp download
    failure should be reported as-is (site is supported but the download
    itself failed) rather than falling back to a raw-file fetch (which only
    makes sense for a plain direct video/audio URL yt-dlp doesn't recognize)."""
    for ie in yt_dlp_extractor.gen_extractor_classes():
        if ie.IE_NAME == "generic":
            continue
        try:
            if ie.suitable(url):
                return True
        except Exception:
            pass
    return False


class MediaError(Exception):
    pass


class UnsupportedLinkError(MediaError):
    pass


class VideoTooLongError(MediaError):
    def __init__(self, duration: float):
        self.duration = duration
        super().__init__(
            f"Video is longer than the {MAX_DURATION_SECONDS // 60} minute limit for this tool."
        )


def probe_url(url: str) -> dict | None:
    """
    Best-effort cheap metadata fetch (duration, title) without downloading.
    Returns None on any failure - this is only used for an early duration
    check, so a failure here must NOT be treated as "site unsupported"
    (that used to trigger a broken fallback that downloaded raw HTML as if
    it were a media file). The real download attempt below has its own,
    more reliable error handling.
    """
    opts = {**_ytdlp_base_opts(), "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    return {"duration": info.get("duration"), "title": info.get("title")}


def download_via_ytdlp(url: str, job_id: str) -> Path:
    out_template = str(DOWNLOADS_DIR / f"{job_id}.%(ext)s")
    opts = {
        **_ytdlp_base_opts(),
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except Exception as e:
        raise MediaError(
            "Could not access this video. It may be private, deleted, "
            "region-locked, or age-restricted."
        ) from e
    if not path.exists():
        raise MediaError("Download completed but the output file was not found.")
    return path


_UNSUPPORTED_MESSAGE = (
    "This link isn't supported. Try a YouTube/TikTok/Facebook link, "
    "a direct video file URL, or upload the file directly."
)


def download_direct_url(url: str, job_id: str) -> Path:
    """Last-resort fallback: fetch the URL as a raw file. Only used after
    yt-dlp itself fails, e.g. for a plain link straight to a video/audio file."""
    suffix = Path(url.split("?")[0]).suffix or ".bin"
    dest = DOWNLOADS_DIR / f"{job_id}{suffix}"
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if not (
                content_type.startswith("video/")
                or content_type.startswith("audio/")
                or content_type == "application/octet-stream"
            ):
                raise UnsupportedLinkError(_UNSUPPORTED_MESSAGE)
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    except httpx.HTTPError as e:
        raise UnsupportedLinkError(_UNSUPPORTED_MESSAGE) from e
    return dest


def fetch_url(url: str, job_id: str) -> Path:
    info = probe_url(url)
    if info:
        duration = info.get("duration")
        if duration and duration > MAX_DURATION_SECONDS:
            raise VideoTooLongError(duration)

    try:
        return download_via_ytdlp(url, job_id)
    except MediaError:
        if _is_known_site(url):
            raise
        return download_direct_url(url, job_id)


async def save_upload(upload_file, job_id: str, max_bytes: int) -> Path:
    suffix = Path(upload_file.filename or "").suffix or ".bin"
    dest = Path(str(DOWNLOADS_DIR / f"{job_id}{suffix}"))
    total = 0
    with open(dest, "wb") as f:
        while chunk := await upload_file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                f.close()
                dest.unlink(missing_ok=True)
                raise MediaError(
                    f"File exceeds the {max_bytes // (1024 * 1024)}MB upload limit."
                )
            f.write(chunk)
    return dest
