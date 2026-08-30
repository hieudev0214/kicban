from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import auth, db, jobs, ratelimit
from app.config import MAX_UPLOAD_BYTES, PRICE_PER_JOB_VND
from app.exporters import to_srt, to_txt
from app.media import MediaError, save_upload
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


def _charge_or_reject(user_id: str) -> None:
    if not db.try_charge_wallet(user_id, PRICE_PER_JOB_VND):
        raise HTTPException(
            402,
            f"Số dư ví không đủ (cần {PRICE_PER_JOB_VND:,} VND). Vui lòng nạp thêm tiền.",
        )


def _own_job_or_404(job: dict | None, user: dict) -> dict:
    if job is None or (user["role"] != "admin" and job["user_id"] != user["id"]):
        raise HTTPException(404, "Job not found.")
    return job


@router.post("", status_code=202)
def create_url_job(body: CreateUrlJob, request: Request, user: dict = Depends(auth.require_user)):
    _check_rate_limit(request)
    if not body.url.strip():
        raise HTTPException(400, "URL is required.")
    _reject_youtube(body.url)
    _charge_or_reject(user["id"])
    job_id = db.create_job(user["id"], "url", body.url.strip(), body.language, PRICE_PER_JOB_VND)
    jobs.enqueue(job_id)
    return {"job_id": job_id}


@router.post("/upload", status_code=202)
async def create_upload_job(
    request: Request,
    file: UploadFile,
    language: str = Form("auto"),
    user: dict = Depends(auth.require_user),
):
    _check_rate_limit(request)
    _charge_or_reject(user["id"])
    job_id = db.create_job(user["id"], "upload", file.filename or "upload", language, PRICE_PER_JOB_VND)
    try:
        saved_path = await save_upload(file, job_id, MAX_UPLOAD_BYTES)
    except MediaError as e:
        db.update_job(job_id, status="error", error=str(e), stage_message="Error")
        db.adjust_wallet_balance(user["id"], PRICE_PER_JOB_VND)
        raise HTTPException(413, str(e)) from e
    db.update_job(job_id, source_ref=str(saved_path))
    jobs.enqueue(job_id)
    return {"job_id": job_id}


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
