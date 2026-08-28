from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import db, jobs, ratelimit
from app.config import MAX_UPLOAD_BYTES, OPENAI_ENABLED
from app.exporters import to_srt, to_txt
from app.media import MediaError, save_upload
from app.transcribe import Segment

router = APIRouter(prefix="/api/jobs")


class CreateUrlJob(BaseModel):
    url: str
    language: str = "auto"
    engine: str = "local"


def _validate_engine(engine: str) -> None:
    if engine not in ("local", "openai"):
        raise HTTPException(400, "Invalid engine.")
    if engine == "openai" and not OPENAI_ENABLED:
        raise HTTPException(400, "OpenAI engine is not configured on this server.")


def _check_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    if not ratelimit.check_and_record(client_ip):
        raise HTTPException(
            429, "Too many requests. Please wait before submitting another job."
        )


@router.post("", status_code=202)
def create_url_job(body: CreateUrlJob, request: Request):
    _validate_engine(body.engine)
    _check_rate_limit(request)
    if not body.url.strip():
        raise HTTPException(400, "URL is required.")
    job_id = db.create_job("url", body.url.strip(), body.engine, body.language)
    jobs.enqueue(job_id, body.engine)
    return {"job_id": job_id}


@router.post("/upload", status_code=202)
async def create_upload_job(
    request: Request,
    file: UploadFile,
    language: str = Form("auto"),
    engine: str = Form("local"),
):
    _validate_engine(engine)
    _check_rate_limit(request)
    job_id = db.create_job("upload", file.filename or "upload", engine, language)
    try:
        saved_path = await save_upload(file, job_id, MAX_UPLOAD_BYTES)
    except MediaError as e:
        db.update_job(job_id, status="error", error=str(e), stage_message="Error")
        raise HTTPException(413, str(e)) from e
    db.update_job(job_id, source_ref=str(saved_path))
    jobs.enqueue(job_id, engine)
    return {"job_id": job_id}


@router.get("")
def list_jobs(limit: int = 20):
    return db.list_jobs(limit=limit)


@router.get("/{job_id}")
def get_job(job_id: str):
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@router.get("/{job_id}/download")
def download_job(job_id: str, fmt: str = "txt"):
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
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
