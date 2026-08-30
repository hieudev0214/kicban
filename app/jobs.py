import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import db, pricing
from app.audio import AudioError, normalize_to_wav, probe
from app.config import AUDIO_DIR, MAX_DURATION_SECONDS
from app.media import MediaError, fetch_url
from app.transcribe import get_transcriber

logger = logging.getLogger("kicban.jobs")

# All jobs use the OpenAI engine now (the local faster-whisper engine was
# removed), so there's no GPU/CPU hardware contention to serialize around -
# a small thread pool is enough.
_job_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="job")

STAGE_FETCHING = "Fetching media..."
STAGE_TRANSCRIBING = "Transcribing (this can take a while for long videos)..."


def enqueue(job_id: str) -> None:
    _job_pool.submit(_run_job, job_id)


def _refund(job: dict) -> None:
    if job["price_vnd"] > 0:
        db.adjust_wallet_balance(job["user_id"], job["price_vnd"])
        logger.info("Refunded %s VND to user %s for failed job %s", job["price_vnd"], job["user_id"], job["id"])
    else:
        # price_vnd == 0 only happens via the free trial (every paid tier is
        # > 0) - give it back so a failed job doesn't burn the user's one
        # free try, same principle as the paid refund above.
        db.restore_free_trial(job["user_id"])
        logger.info("Restored free trial for user %s after failed job %s", job["user_id"], job["id"])


def _reconcile_price(job_id: str, job: dict, actual_duration: float) -> None:
    """A job charged with an unknown duration (yt-dlp's metadata probe
    failed) is charged the highest tier up front as a safe upper bound. Now
    that the real duration is known, refund the difference if that turned
    out to be an overcharge. Never charges more on the other side - a low
    estimate is not expected to happen since known-duration jobs are already
    charged their exact tier, and trying to collect more mid-job risks
    failing on insufficient balance."""
    if job["price_vnd"] <= 0:
        return
    true_price = pricing.price_for_duration_seconds(actual_duration)
    if true_price < job["price_vnd"]:
        refund_amount = job["price_vnd"] - true_price
        db.adjust_wallet_balance(job["user_id"], refund_amount)
        db.update_job(job_id, price_vnd=true_price)
        job["price_vnd"] = true_price
        logger.info(
            "Reconciled job %s price down to %s VND, refunded %s VND (actual duration %.1fs)",
            job_id, true_price, refund_amount, actual_duration,
        )


def _run_job(job_id: str) -> None:
    job = db.get_job(job_id)
    if job is None:
        return
    try:
        db.update_job(job_id, status="fetching", stage_message=STAGE_FETCHING)

        if job.get("prefetched_path"):
            # routes/api.py already downloaded this one to measure its real
            # duration before charging (the cheap metadata probe couldn't
            # determine it up front) - don't fetch it a second time.
            media_path = Path(job["prefetched_path"])
        elif job["source_type"] == "url":
            media_path = fetch_url(job["source_ref"], job_id, known_duration=job.get("duration_seconds"))
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
        _reconcile_price(job_id, job, info["duration"])

        db.update_job(job_id, status="transcribing", stage_message=STAGE_TRANSCRIBING)
        transcriber = get_transcriber()
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
        _refund(job)
    except Exception:
        logger.exception("Job %s failed", job_id)
        db.update_job(
            job_id,
            status="error",
            error="Something went wrong while processing this job.",
            stage_message="Error",
        )
        _refund(job)
