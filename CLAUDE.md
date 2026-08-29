# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

kicban is a small FastAPI web app: paste a video link (YouTube/TikTok/Facebook/direct URL) or upload
a video/audio file, and it transcribes speech to text. Two STT engines are selectable: **local**
(`faster-whisper`, free, runs on-machine) or **OpenAI API** (paid, faster for high volume).

README and code comments are written in Vietnamese; match that when editing docs/comments in this repo.

## Commands

```bash
uv sync                                    # install deps (pins Python 3.12 via uv)
cp .env.example .env                       # then edit WHISPER_MODEL / OPENAI_API_KEY as needed
uv run uvicorn app.main:app --reload       # run dev server -> http://localhost:8000
uv run pytest                              # run all tests
uv run pytest tests/test_exporters.py -k test_to_srt_formats_timestamps_and_index  # single test
docker build -t kicban .                   # build production image
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... kicban
```

System requirements: `ffmpeg`/`ffprobe` on PATH (audio extraction/probing). Optional NVIDIA GPU +
CUDA Toolkit for faster local transcription — the app auto-falls-back to CPU if CUDA libs are missing.

## Architecture

**Request flow**: `routes/pages.py` serves the single-page UI (`templates/index.html`); `routes/api.py`
exposes `/api/jobs` (create by URL or upload, list, get status, download `.txt`/`.srt`). Job creation
returns immediately (202) with a `job_id` — the frontend polls `GET /api/jobs/{id}` for status.

**Job pipeline** (`jobs.py` → `media.py` → `audio.py` → `transcribe.py`, state in `db.py`):
1. `db.create_job` inserts a row with status `queued`.
2. `jobs.enqueue` routes by engine: `local` jobs go on a single-threaded `queue.Queue` (one worker
   thread — GPU/CPU-bound, must run strictly sequentially); `openai` jobs go to a 3-worker
   `ThreadPoolExecutor` (no local hardware contention, so they can run concurrently with each other
   and with the local job).
3. `_run_job` in `jobs.py` drives the pipeline for both paths: fetch media (`media.fetch_url` for URLs,
   or the already-saved upload path) → `audio.normalize_to_wav` (ffmpeg, extracts mono 16kHz PCM) →
   re-check duration against `MAX_DURATION_SECONDS` (yt-dlp duration metadata can be missing/wrong
   up front, so this is a safety-net re-check after the real probe) → `transcribe.get_transcriber(engine)`
   → write transcript/segments/status back via `db.update_job`.
4. Errors are split into two tiers: known `MediaError`/`AudioError` write their message straight to
   the job (user-facing); anything else is logged with `exc_info` and a generic message is stored
   instead, so internals never leak to the client.

**Media fetch** (`media.py`): `fetch_url` first does a cheap `probe_url` (yt-dlp, `skip_download`) for
an early duration check — a probe failure is *not* treated as "unsupported," since that used to cause
a broken fallback that downloaded raw HTML as if it were a media file. It then tries `download_via_ytdlp`;
if that fails, `_is_known_site` checks whether a non-generic yt-dlp extractor recognizes the URL — if so
the yt-dlp error is re-raised as-is (real failure, not an unsupported link), otherwise it falls back to
`download_direct_url` (plain `httpx` GET, only accepted if the response `Content-Type` is video/audio/
octet-stream). This distinction matters: don't collapse these two failure paths back together.

**Cookies for yt-dlp** (also in `media.py`): cloud/datacenter IPs get bot-blocked by YouTube/TikTok, so
production deployments set `YTDLP_COOKIES_FILE` (default, used for TikTok/Facebook/etc.) and optionally
`YTDLP_COOKIES_FILE_YOUTUBE` (YouTube only) to Netscape-format cookies files — `_cookies_source_for`
picks the right one by checking if the URL is a youtube.com/youtu.be domain. **These must stay in
separate files, never merged into one**: combining TikTok's and YouTube's cookies into a single
cookies.txt was found in practice to break TikTok's anti-bot challenge extraction even though each
worked fine alone. Because yt-dlp rewrites the cookiefile on every `close()`, and hosts like Render
mount the configured file read-only (Secret Files), each source file is copied once to its own writable
runtime path (`data/cookies_runtime_<sha1-prefix-of-source-path>.txt`) and that copy is what's actually
passed to yt-dlp.

**YouTube PO Token workaround**: `_ytdlp_base_opts` forces `extractor_args.youtube.player_client` to try
`android`/`ios` before `web`, because YouTube's web client requires a PO Token that yt-dlp can't obtain
from a datacenter IP without a separate token-provider service; the android/ios clients are checked for
this less often. This is a partial mitigation, not a full fix — YouTube can still reject the actual
format/media URL with "Requested format is not available" even after extraction succeeds, since PO
Token enforcement happens at multiple stages. A real fix would need a PO token provider (extra
service), which hasn't been added.

**Retry on download** (`download_via_ytdlp`): TikTok's (and sometimes YouTube's) bot challenge is flaky
rather than a hard block — the same URL and cookies can fail on one attempt and succeed on the next.
The function retries up to `_MAX_YTDLP_ATTEMPTS` (3) times with a `_RETRY_DELAY_SECONDS` (3s) pause
before giving up and raising the generic "Could not access this video" `MediaError`.

**Transcription** (`transcribe.py`): both engines implement the same `Transcriber` protocol
(`transcribe(wav_path, language) -> TranscriptionResult`). `FasterWhisperTranscriber` is a
process-wide singleton (class-level `_model`, guarded by a lock) — the model loads once, lazily.
GPU→CPU fallback is handled at *two* points because CUDA fails two different ways: no NVIDIA driver
at all fails at `WhisperModel()` construction, while a present driver with missing CUDA Toolkit libs
(cuBLAS/cuDNN) only fails on the first inference call (`RuntimeError`), so there's a fallback both in
`_get_model` and around the first `model.transcribe()` call. `OpenAITranscriber` only requests
`verbose_json` (needed for per-segment timestamps / `.srt` export) from models in `_VERBOSE_JSON_MODELS`
(currently just `whisper-1`) — other models (e.g. `gpt-4o-transcribe`) only support plain `json` and
come back as one synthetic zero-timestamp segment.

**Storage**: SQLite at `data/jobs.db` (single connection, `check_same_thread=False`, guarded by a
module-level `threading.Lock` in `db.py` — every query goes through that lock). One `jobs` table holds
full job state including the transcript and JSON-encoded segments; there are no migrations, schema
changes are hand-edited `CREATE TABLE IF NOT EXISTS` changes. Working files live under `data/`
(`uploads/`, `downloads/`, `audio/`) and are named by `job_id`; local Whisper model weights cache in
`models/`. On Render's free tier this disk is ephemeral, so job history (not transcription capability)
is lost on redeploy unless a persistent disk is attached.

**Config** (`config.py`): all environment-derived settings and directory constants live here as
module-level globals, loaded once via `load_dotenv()` at import time. `OPENAI_ENABLED` gates whether
the OpenAI engine option appears/works at all — it's derived from whether `OPENAI_API_KEY` is set,
not a separate flag.

**Rate limiting** (`ratelimit.py`): in-memory per-IP sliding window (`MAX_JOBS_PER_HOUR_PER_IP`,
default 5/hour) to bound OpenAI API spend on public deployments. State is a plain dict guarded by a
lock — it resets on process restart and does not work across multiple server instances.
