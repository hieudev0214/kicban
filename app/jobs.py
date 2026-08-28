import json
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import db
from app.audio import AudioError, normalize_to_wav, probe
from app.config import AUDIO_DIR, MAX_DURATION_SECONDS
from app.media import MediaError, fetch_url
from app.transcribe import get_transcriber

logger = logging.getLogger("kicban.jobs")

# Local (GPU-bound) jobs run strictly one at a time via this queue + single worker
# thread. OpenAI jobs don't touch local hardware, so they get their own small
# thread pool and can run concurrently with each other and with the local job.
_local_queue: "queue.Queue[str]" = queue.Queue()
_openai_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="openai-job")

STAGE_FETCHING = "Fetching media..."
STAGE_TRANSCRIBING = "Transcribing (this can take a while for long videos)..."


def enqueue(job_id: str, engine: str) -> None:
    if engine == "openai":
        _openai_pool.submit(_run_job, job_id)
    else:
        _local_queue.put(job_id)


def _run_job(job_id: str) -> None:
    job = db.get_job(job_id)
    if job is None:
        return
    try:
        db.update_job(job_id, status="fetching", stage_message=STAGE_FETCHING)

        if job["source_type"] == "url":
            media_path = fetch_url(job["source_ref"], job_id)
        else:
            media_path = Path(job["source_ref"])

        wav_path = AUDIO_DIR / f"{job_id}.wav"
        normalize_to_wav(media_path, wav_path)

        # Safety-net re-check: yt-dlp metadata duration may be missing/unknown
        # up front for direct URLs or some uploads.
        info = probe(wav_path)
        if info["duration"] > MAX_DURATION_SECONDS:
            raise MediaError(
                f"Video is longer than the {MAX_DURATION_SECONDS // 60} minute limit for this tool."
            )

        db.update_job(job_id, status="transcribing", stage_message=STAGE_TRANSCRIBING)
        transcriber = get_transcriber(job["engine"])
        result = transcriber.transcribe(wav_path, job["language"])

        if not result.text.strip():
            db.update_job(
                job_id,
                status="done",
                stage_message="No speech was detected in this media.",
                transcript_text="",
                language_detected=result.language,
                segments_json=json.dumps([]),
            )
            return

        segments_json = json.dumps(
            [{"start": s.start, "end": s.end, "text": s.text} for s in result.segments]
        )
        db.update_job(
            job_id,
            status="done",
            stage_message="Done",
            transcript_text=result.text,
            language_detected=result.language,
            segments_json=segments_json,
        )
    except (MediaError, AudioError) as e:
        logger.warning("Job %s failed with a known error: %s", job_id, e, exc_info=True)
        db.update_job(job_id, status="error", error=str(e), stage_message="Error")
    except Exception:
        logger.exception("Job %s failed", job_id)
        db.update_job(
            job_id,
            status="error",
            error="Something went wrong while processing this job.",
            stage_message="Error",
        )


def _local_worker_loop() -> None:
    while True:
        job_id = _local_queue.get()
        try:
            _run_job(job_id)
        finally:
            _local_queue.task_done()


def start_worker() -> None:
    thread = threading.Thread(target=_local_worker_loop, daemon=True, name="local-job-worker")
    thread.start()
