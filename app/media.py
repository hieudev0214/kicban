import hashlib
import logging
import shutil
import threading
import time
from pathlib import Path

import httpx
import yt_dlp
import yt_dlp.extractor as yt_dlp_extractor

from app.config import (
    DATA_DIR,
    DOWNLOADS_DIR,
    MAX_DURATION_SECONDS,
    YTDLP_COOKIES_FILE,
    YTDLP_COOKIES_FILE_YOUTUBE,
)

logger = logging.getLogger("kicban.media")

_cookies_lock = threading.Lock()
_runtime_cookie_paths: dict[str, Path] = {}


def _cookies_source_for(url: str) -> str | None:
    """Pick which configured cookies file applies to this URL. Kept separate
    per site rather than merged into one file: combining TikTok's and
    YouTube's cookies into a single cookies.txt was observed to break
    TikTok's extraction, so each site gets its own runtime copy."""
    if "youtube.com" in url or "youtu.be" in url:
        return YTDLP_COOKIES_FILE_YOUTUBE or YTDLP_COOKIES_FILE
    return YTDLP_COOKIES_FILE


def _writable_cookies_path(source_file: str | None) -> str | None:
    """yt-dlp rewrites the cookiefile on every close() to persist updated
    cookies. On Render, a cookies file points at a Secret File mount
    (/etc/secrets/...), which is read-only - that write fails and raises an
    OSError that masks the real download error (or even fails an otherwise
    successful download). Work around it by copying the configured cookies
    file to a writable path once per source file and using that copy."""
    if not source_file:
        return None
    with _cookies_lock:
        runtime_path = _runtime_cookie_paths.get(source_file)
        if runtime_path is None:
            digest = hashlib.sha1(source_file.encode()).hexdigest()[:8]
            runtime_path = DATA_DIR / f"cookies_runtime_{digest}.txt"
            _runtime_cookie_paths[source_file] = runtime_path
        if not runtime_path.exists():
            shutil.copyfile(source_file, runtime_path)
    return str(runtime_path)


def _ytdlp_base_opts(url: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # YouTube requires a PO Token for the "web" client when the request
        # comes from a datacenter/cloud IP (e.g. Render), which yt-dlp can't
        # obtain without a separate token-provider service. The android/ios
        # clients are checked less often, so try them first and fall back to
        # web for sites where this doesn't apply.
        "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
    }
    cookies_path = _writable_cookies_path(_cookies_source_for(url))
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


# TikTok's (and sometimes YouTube's) anti-bot challenge is flaky rather than
# a hard block: the same URL can fail on one request and succeed on the next
# from the same IP/cookies. A few retries with a short delay recovers most
# of these transient failures without needing extra infrastructure. Used by
# both probe_url (duration lookup for pricing) and download_via_ytdlp below.
_MAX_YTDLP_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 3


def probe_url(url: str) -> dict | None:
    """
    Best-effort cheap metadata fetch (duration, title) without downloading.
    Retries like download_via_ytdlp does - a probe hits the same flaky
    bot-challenge as a real download, and this result now drives up-front
    pricing (see routes/api.py), so a transient failure here previously
    meant charging the highest tier for videos whose real duration was
    knowable all along. Returns None only once every attempt has failed -
    this is used for an early duration check, so a failure here must NOT be
    treated as "site unsupported" (that used to trigger a broken fallback
    that downloaded raw HTML as if it were a media file).
    """
    opts = {**_ytdlp_base_opts(url), "skip_download": True}
    for attempt in range(1, _MAX_YTDLP_ATTEMPTS + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return {"duration": info.get("duration"), "title": info.get("title")}
        except Exception as e:
            if attempt < _MAX_YTDLP_ATTEMPTS:
                logger.warning(
                    "yt-dlp probe attempt %d/%d failed for %s, retrying: %s",
                    attempt, _MAX_YTDLP_ATTEMPTS, url, e,
                )
                time.sleep(_RETRY_DELAY_SECONDS)
    return None


def download_via_ytdlp(url: str, job_id: str) -> Path:
    out_template = str(DOWNLOADS_DIR / f"{job_id}.%(ext)s")
    opts = {
        **_ytdlp_base_opts(url),
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
    }
    last_error: Exception | None = None
    for attempt in range(1, _MAX_YTDLP_ATTEMPTS + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = Path(ydl.prepare_filename(info))
            if not path.exists():
                raise MediaError("Download completed but the output file was not found.")
            return path
        except Exception as e:
            last_error = e
            if attempt < _MAX_YTDLP_ATTEMPTS:
                logger.warning(
                    "yt-dlp download attempt %d/%d failed for job %s, retrying: %s",
                    attempt, _MAX_YTDLP_ATTEMPTS, job_id, e,
                )
                time.sleep(_RETRY_DELAY_SECONDS)
    raise MediaError(
        "Could not access this video. It may be private, deleted, "
        "region-locked, or age-restricted."
    ) from last_error


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


def download_media(url: str, job_id: str) -> Path:
    """Download only, no duration check - split out of fetch_url so a caller
    that already knows the probe can't determine this URL's duration (see
    routes/api.py) can download straight to disk and measure the real
    duration with ffprobe afterward, instead of guessing a price up front."""
    try:
        return download_via_ytdlp(url, job_id)
    except MediaError:
        if _is_known_site(url):
            raise
        return download_direct_url(url, job_id)


def fetch_url(url: str, job_id: str, known_duration: float | None = None) -> Path:
    """`known_duration` lets a caller that already probed this URL (routes/api.py
    does, to quote a price before charging) skip probing it again here - probe_url
    now retries on failure, so re-running it unconditionally would double the
    worst-case latency for no benefit. Passed as None when duration wasn't
    determined up front, in which case this probes as before."""
    duration = known_duration
    if duration is None:
        info = probe_url(url)
        duration = info.get("duration") if info else None
    if duration and duration > MAX_DURATION_SECONDS:
        raise VideoTooLongError(duration)

    return download_media(url, job_id)


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
