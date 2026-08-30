from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import auth, db, jobs, pricing, ratelimit
from app.audio import AudioError, probe as probe_audio
from app.config import MAX_DURATION_SECONDS, MAX_UPLOAD_BYTES
from app.exporters import to_srt, to_txt
from app.media import MediaError, download_media, probe_url, save_upload
from app.transcribe import Segment

router = APIRouter(prefix="/api/jobs")


class CreateUrlJob(BaseModel):
    url: str
    language: str = "auto"


def _reject_youtube(url: str) -> None:
    lowered = url.lower()
    if "youtube.com" in lowered or "youtu.be" in lowered:
        raise HTTPException(
            400,
            "YouTube tạm thời chưa được hỗ trợ. Vui lòng dùng link TikTok/Facebook, "
            "URL video trực tiếp, hoặc tải file lên.",
        )


def _check_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    if not ratelimit.check_and_record(client_ip):
        raise HTTPException(
            429, "Too many requests. Please wait before submitting another job."
        )


def _price_for(user_id: str, duration: float | None) -> int:
    """Consume the user's free trial if this job qualifies for it, otherwise
    return the tiered price for this duration (charging happens separately -
    see _charge)."""
    if pricing.is_free_trial_eligible(duration) and db.try_use_free_trial(user_id):
        return 0
    return pricing.price_for_duration_seconds(duration)


def _charge(user_id: str, price_vnd: int) -> None:
    if price_vnd > 0 and not db.try_charge_wallet(user_id, price_vnd):
        raise HTTPException(
            402,
            f"Số dư ví không đủ (cần {price_vnd:,} VND). Vui lòng nạp thêm tiền.",
        )


def _own_job_or_404(job: dict | None, user: dict) -> dict:
    if job is None or (user["role"] != "admin" and job["user_id"] != user["id"]):
        raise HTTPException(404, "Job not found.")
    return job


@router.post("", status_code=202)
def create_url_job(body: CreateUrlJob, request: Request, user: dict = Depends(auth.require_user)):
    _check_rate_limit(request)
    url = body.url.strip()
    if not url:
        raise HTTPException(400, "URL is required.")
    _reject_youtube(url)

    info = probe_url(url)
    duration = info.get("duration") if info else None
    if duration and duration > MAX_DURATION_SECONDS:
        raise HTTPException(
            400, f"Video is longer than the {MAX_DURATION_SECONDS // 60} minute limit for this tool."
        )

    job_id = db.create_job(user["id"], "url", url, body.language, 0)
    prefetched_path: Path | None = None

    if duration is None:
        # The cheap metadata probe couldn't determine the duration even
        # after retries (TikTok's bot-challenge can outright block it) -
        # rather than charging a pessimistic highest-tier estimate and
        # possibly rejecting someone who can actually afford the real
        # (lower) price, download the media now - no OpenAI cost yet, only
        # server bandwidth - so ffprobe can measure it exactly before
        # anything is charged.
        try:
            prefetched_path = download_media(url, job_id)
        except MediaError as e:
            db.update_job(job_id, status="error", error=str(e), stage_message="Error")
            raise HTTPException(400, str(e)) from e
        try:
            duration = probe_audio(prefetched_path)["duration"]
        except AudioError:
            duration = None
        if duration and duration > MAX_DURATION_SECONDS:
            message = f"Video is longer than the {MAX_DURATION_SECONDS // 60} minute limit for this tool."
            db.update_job(job_id, status="error", error=message, stage_message="Error")
            raise HTTPException(400, message)

    price = _price_for(user["id"], duration)
    try:
        _charge(user["id"], price)
    except HTTPException:
        if prefetched_path:
            prefetched_path.unlink(missing_ok=True)
        db.update_job(job_id, status="error", error="Insufficient balance.", stage_message="Error")
        raise

    db.update_job(
        job_id,
        price_vnd=price,
        duration_seconds=duration,
        prefetched_path=str(prefetched_path) if prefetched_path else None,
    )
    jobs.enqueue(job_id)
    return {"job_id": job_id, "price_vnd": price, "duration_seconds": duration}


@router.post("/upload", status_code=202)
async def create_upload_job(
    request: Request,
    file: UploadFile,
    language: str = Form("auto"),
    user: dict = Depends(auth.require_user),
):
    _check_rate_limit(request)
    job_id = db.create_job(user["id"], "upload", file.filename or "upload", language, 0)
    try:
        saved_path = await save_upload(file, job_id, MAX_UPLOAD_BYTES)
    except MediaError as e:
        db.update_job(job_id, status="error", error=str(e), stage_message="Error")
        raise HTTPException(413, str(e)) from e

    try:
        duration = probe_audio(saved_path)["duration"]
    except AudioError:
        duration = None

    price = _price_for(user["id"], duration)
    try:
        _charge(user["id"], price)
    except HTTPException:
        saved_path.unlink(missing_ok=True)
        db.update_job(job_id, status="error", error="Insufficient balance.", stage_message="Error")
        raise

    db.update_job(job_id, source_ref=str(saved_path), price_vnd=price, duration_seconds=duration)
    jobs.enqueue(job_id)
    return {"job_id": job_id, "price_vnd": price, "duration_seconds": duration}


@router.get("")
def list_jobs(limit: int = 20, user: dict = Depends(auth.require_user)):
    return db.list_jobs_for_user(user["id"], limit=limit)


@router.get("/{job_id}")
def get_job(job_id: str, user: dict = Depends(auth.require_user)):
    job = _own_job_or_404(db.get_job(job_id), user)
    return job


@router.get("/{job_id}/download")
def download_job(job_id: str, fmt: str = "txt", user: dict = Depends(auth.require_user)):
    job = _own_job_or_404(db.get_job(job_id), user)
    if job["status"] != "done":
        raise HTTPException(400, "Job is not finished yet.")

    if fmt == "txt":
        content = to_txt(job["transcript_text"] or "")
        media_type = "text/plain"
    elif fmt == "srt":
        segments = [Segment(**s) for s in (job["segments"] or [])]
        content = to_srt(segments)
        media_type = "text/plain"
    else:
        raise HTTPException(400, "fmt must be 'txt' or 'srt'.")

    return PlainTextResponse(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{job_id}.{fmt}"'},
    )
