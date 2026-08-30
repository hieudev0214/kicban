# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

kicban is a FastAPI web app: users register/log in, top up a wallet via manual bank transfer (scan a
VietQR code, an admin confirms and credits it - see "Manual bank-transfer top-up" below), then paste a
video link (TikTok/Facebook/direct URL) or upload a video/audio file to get speech transcribed to text
via the OpenAI API. Each transcription job deducts a price tiered by media duration from the user's
wallet (see "Wallet & pricing" below), refunded automatically if the job fails. A new account's first
job is free (short videos only). There's an admin panel (`/admin`) to approve/reject top-up requests,
view users/jobs, manually adjust wallet balances, and lock/delete accounts.

**No payment gateway (VNPay, MoMo, PayOS, ...) is integrated, and this was a deliberate choice, not an
oversight**: every one of them requires identity/business-verified merchant onboarding before issuing
API credentials (an AML/KYC legal requirement, not something any provider can skip), which blocked
getting the app usable quickly. A VNPay integration (`vnpay.py`, HMAC-SHA512 signed URLs + IPN webhook)
was built and verified working end-to-end in an earlier pass of this session, then deleted once VNPay's
merchant sandbox registration turned out to be stuck in an identity-verification flow with no clear
self-service path. If a payment gateway is wanted again later, that VNPay algorithm write-up is still
useful reference (see git history for `vnpay.py` / `tests/test_vnpay.py`), but don't assume it's what
the user wants without asking - the manual flow was a deliberate fallback, not a stopgap to silently
replace.

**YouTube is temporarily unsupported** — blocked at the API layer (`routes/api.py`'s `_reject_youtube`)
because YouTube enforces a PO Token requirement on datacenter IPs that this app doesn't yet work
around (see "YouTube PO Token" below); the underlying yt-dlp/cookie code for it is left in place,
just unreachable, so it can be re-enabled later without rebuilding it. **The local `faster-whisper`
engine was removed entirely** (this is now a paid product — OpenAI is the only engine) — don't
reintroduce it without being asked.

README and code comments are written in Vietnamese; match that when editing docs/comments in this repo.

## Commands

```bash
uv sync                                    # install deps (pins Python 3.12 via uv)
cp .env.example .env                       # then edit OPENAI_API_KEY / SECRET_KEY / ADMIN_EMAILS / BANK_*
uv run uvicorn app.main:app --reload       # run dev server -> http://localhost:8000
uv run pytest                              # run all tests
docker build -t kicban .                   # build production image
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... -e SECRET_KEY=... kicban
```

System requirements: `ffmpeg`/`ffprobe` on PATH (audio extraction/probing). `OPENAI_API_KEY` is
mandatory now (no local fallback). `SECRET_KEY` must be a long random value in production - it signs
session cookies, so a leaked/default value lets anyone forge a login session.

## Architecture

**Request flow**: `routes/pages.py` serves server-rendered pages (`/`, `/login`, `/register`, `/admin`)
via Jinja2 templates; `routes/api.py` exposes `/api/jobs` (create by URL or upload, list, get status,
download `.txt`/`.srt`) - all gated behind login; `routes/auth.py` exposes `/api/auth/*`
(register/login/logout/me); `routes/wallet.py` exposes `/api/wallet/*` (create a top-up request + get
its VietQR code, list the current user's own top-up history); `routes/admin.py` exposes `/api/admin/*`
(admin-only user management, plus listing/approving/rejecting top-up requests). Job creation returns
immediately (202) with a `job_id` - the frontend polls `GET /api/jobs/{id}` for status.

**Auth** (`auth.py`): passwords are hashed with `bcrypt`. Sessions are a single signed cookie
(`itsdangerous.URLSafeTimedSerializer`, `SECRET_KEY`-keyed, `SESSION_MAX_AGE_SECONDS` = 30 days) -
there is no server-side session table, the cookie itself carries `{"user_id": ...}` and is
self-verifying, so logout is just clearing the cookie. `get_current_user` additionally re-checks
`is_locked` on every request against the DB (not baked into the cookie), so an admin lock takes effect
immediately without waiting for the session to expire. `require_user`/`require_admin` are FastAPI
`Depends()` dependencies; a locked or missing session surfaces as a plain 401 from `require_user`
(not a distinct "you're locked" message) to avoid leaking account-existence info.

**Admin bootstrap**: there's no "create admin" UI or CLI - `ADMIN_EMAILS` (comma-separated env var) is
checked on both register and login; a matching email is promoted to `role="admin"` on the spot. This
is the only way to create the first admin account.

**Wallet & pricing** (`pricing.py`): price is **tiered by media duration**, not a flat amount - `TIERS`
is a hardcoded list of `(upper_bound_seconds, price_vnd)` pairs (e.g. ≤2 min = 3,000đ, up to ≤120 min =
70,000đ, matching `MAX_DURATION_SECONDS`). This replaced an earlier flat `PRICE_PER_JOB_VND`: Whisper's
real cost scales with audio length (~$0.006/min), so one flat price either overcharged short clips or
lost money on long ones (a 2-hour video cost ~18,000đ to transcribe but a flat 5,000đ charge wouldn't
cover it). Each tier is priced well above its worst-case cost, so no tier can lose money even at its
upper bound. `routes/api.py` determines the price **before** charging: for a URL job it calls
`media.probe_url` (cheap yt-dlp metadata fetch, no download) to get the duration up front - this makes
job creation noticeably slower than before (a real network call instead of just DB writes), a deliberate
trade for accurate pricing; for an upload it runs `audio.probe` (ffprobe) on the already-saved file. If
duration can't be determined at charge time (a URL probe failure), `pricing.price_for_duration_seconds`
falls back to the highest tier as a safe upper bound, and `jobs.py`'s `_reconcile_price` (called after
the pipeline's own post-download duration check) refunds the difference once the real duration is known
- charging conservatively high and refunding down is simpler and safer than trying to collect more from
the wallet mid-job. `try_charge_wallet` does the balance-check-and-deduct as one operation under `db.py`'s
existing write lock - this closes the race where two concurrent job submissions could both pass a
balance check before either deduction lands. `jobs.py`'s `_refund` refunds `job["price_vnd"]` back to
the wallet automatically on any failure path (`MediaError`/`AudioError` or an unhandled exception) - so
a user is only ever charged for a job that actually produced a transcript.

**Free trial**: a brand-new account gets one free transcription (`users.free_trial_used`, consumed
atomically by `db.try_use_free_trial` under the write lock so two simultaneous "first" jobs can't both
claim it), capped to videos ≤ `pricing.FREE_TRIAL_MAX_SECONDS` (10 min) so it can't be used to get a
long - and therefore costly to us - job for free. If that free job fails, `_refund` calls
`db.restore_free_trial` to give the trial back rather than burning it on a job that produced nothing,
mirroring the paid-refund policy above. `/api/auth/me` exposes `free_trial_available` so the frontend
can show a banner.

**Manual bank-transfer top-up** (`vietqr.py` + `routes/wallet.py` + the `topups` table): `POST
/api/wallet/topup-request` creates a `topups` row (`status="pending"`) and generates a short unique
transfer note (`NAP <first 8 chars of the topup id, uppercased>`) the customer must keep in their bank
transfer's content field, so the admin can match it against their bank statement later. `vietqr.py`'s
`build_qr_url` just builds a URL against VietQR's public "quick link" image API
(`img.vietqr.io/image/<BANK_ID>-<BANK_ACCOUNT_NO>-compact2.png?amount=...&addInfo=...&accountName=...`)
- no API key or registration needed, it's a standardized QR any Vietnamese banking app can scan. There
is deliberately **no automatic confirmation** - `POST /api/admin/topups/{id}/approve` (admin-only) is
the only thing that credits `wallet_balance_vnd`, and only after a human checks the real bank statement;
`reject` marks it `rejected` without crediting. Both guard against acting twice on the same request by
checking `status == "pending"` first. `MANUAL_TOPUP_ENABLED` (config.py) is derived from
`BANK_ID`/`BANK_ACCOUNT_NO`/`BANK_ACCOUNT_NAME` all being set - topup-request is a plain 400 if any are
missing rather than generating a QR pointing at nothing.

**Job pipeline** (`jobs.py` → `media.py` → `audio.py` → `transcribe.py`, state in `db.py`): jobs now
all go through one `ThreadPoolExecutor` (`_job_pool`, 3 workers) - there's no more GPU-bound local
queue to serialize around now that faster-whisper is gone. `_run_job` drives fetch media
(`media.fetch_url` for URLs, or the already-saved upload path) → `audio.normalize_to_wav` (ffmpeg,
extracts mono 16kHz PCM) → re-check duration against `MAX_DURATION_SECONDS` → `transcribe.get_transcriber()`
(always `OpenAITranscriber`) → write transcript/segments/status back via `db.update_job`, refunding the
job's price on any failure (see "Wallet & pricing" above). Errors are split into two tiers: known
`MediaError`/`AudioError` write their message straight to the job (user-facing); anything else is
logged with `exc_info` and a generic message is stored instead, so internals never leak to the client.

**Media fetch** (`media.py`): `fetch_url` first does a cheap `probe_url` (yt-dlp, `skip_download`) for
an early duration check - a probe failure is *not* treated as "unsupported," since that used to cause
a broken fallback that downloaded raw HTML as if it were a media file. It then tries `download_via_ytdlp`;
if that fails, `_is_known_site` checks whether a non-generic yt-dlp extractor recognizes the URL - if so
the yt-dlp error is re-raised as-is (real failure, not an unsupported link), otherwise it falls back to
`download_direct_url` (plain `httpx` GET, only accepted if the response `Content-Type` is video/audio/
octet-stream). This distinction matters: don't collapse these two failure paths back together.
**YouTube URLs never reach this module** in the current build - they're rejected earlier in
`routes/api.py` with a "temporarily unsupported" message, so the YouTube-specific code below is dead
in production but intentionally not deleted.

**Cookies for yt-dlp**: cloud/datacenter IPs get bot-blocked by TikTok, so production deployments set
`YTDLP_COOKIES_FILE` to a Netscape-format cookies file — `_cookies_source_for` picks it (or
`YTDLP_COOKIES_FILE_YOUTUBE`, currently unused since YouTube is blocked upstream) by checking the URL's
domain. **These must stay in separate files, never merged into one**: combining TikTok's and YouTube's
cookies into a single cookies.txt was found in practice to break TikTok's anti-bot challenge extraction
even though each worked fine alone. TikTok's cookies were also observed to expire in practice after as
little as ~1 day (much faster than the weeks/months typical of other sites), so expect to refresh them
often. Because yt-dlp rewrites the cookiefile on every `close()`, and hosts like Render mount the
configured file read-only (Secret Files), each source file is copied once to its own writable runtime
path (`data/cookies_runtime_<sha1-prefix-of-source-path>.txt`) and that copy is what's actually passed
to yt-dlp.

**YouTube PO Token** (dormant, see above): `_ytdlp_base_opts` forces `extractor_args.youtube.player_client`
to try `android`/`ios` before `web`, because YouTube's web client requires a PO Token that yt-dlp can't
obtain from a datacenter IP without a separate token-provider service. Verified in practice (this
session) that this mitigation is *insufficient on its own* on a datacenter IP: extraction succeeds but
the actual format/media URL still gets rejected with "Requested format is not available" once YouTube
enforces PO Token on the fallback format too - confirmed both with and without real YouTube cookies. A
real fix needs a PO token provider (e.g. `bgutil-ytdlp-pot-provider`), which is nontrivial to deploy
alongside this app (needs a Node.js sidecar/service - either bundled into the Docker image, which risks
native-dependency breakage from the `canvas` npm package, or run as a second paid Render service) and
has not been added; that tradeoff (extra cost + complexity vs. YouTube support) is a product decision,
not a technical one, so don't just wire it in - check with the user first.

**Retry on download** (`download_via_ytdlp`): TikTok's (and sometimes YouTube's) bot challenge is flaky
rather than a hard block — the same URL and cookies can fail on one attempt and succeed on the next.
The function retries up to `_MAX_YTDLP_ATTEMPTS` (3) times with a `_RETRY_DELAY_SECONDS` (3s) pause
before giving up and raising the generic "Could not access this video" `MediaError`.

**Transcription** (`transcribe.py`): only `OpenAITranscriber` remains, implementing the `Transcriber`
protocol (`transcribe(wav_path, language) -> TranscriptionResult`); `get_transcriber()` takes no
argument now. It only requests `verbose_json` (needed for per-segment timestamps / `.srt` export) from
models in `_VERBOSE_JSON_MODELS` (currently just `whisper-1`) — other models (e.g. `gpt-4o-transcribe`)
only support plain `json` and come back as one synthetic zero-timestamp segment.

**Storage**: SQLite at `data/jobs.db` (single connection, `check_same_thread=False`, guarded by a
module-level `threading.Lock` in `db.py` - every write goes through that lock, including
`try_charge_wallet`'s check-and-deduct, which is why it's race-safe). Three tables: `users`
(email/password_hash/role/wallet_balance_vnd/is_locked/free_trial_used), `topups` (manual top-up requests, keyed by a
unique `note` - the bank transfer content string - with `status` pending/approved/rejected), and `jobs`
(now with `user_id` and `price_vnd`).
There are no migrations - schema changes are hand-edited `CREATE TABLE IF NOT EXISTS` statements, plus
a small `_add_column_if_missing` helper (best-effort `ALTER TABLE`, swallows "duplicate column") used
when a column was added to a table that already existed on someone's disk; this only matters for a
persisted local `data/jobs.db` since Render's free-tier disk is ephemeral and gets a fresh schema on
every redeploy anyway. **Once real users have real money in their wallets, losing this file on
redeploy is a real problem** - a persistent disk becomes necessary at that point, not optional. Working
files live under `data/` (`uploads/`, `downloads/`, `audio/`) and are named by `job_id`.

**Config** (`config.py`): all environment-derived settings live here as module-level globals, loaded
once via `load_dotenv()` at import time. `OPENAI_ENABLED`/`MANUAL_TOPUP_ENABLED` gate whether those
features work at all, derived from whether their required env vars are set rather than a separate flag.

**Rate limiting** (`ratelimit.py`): in-memory per-IP sliding window (`MAX_JOBS_PER_HOUR_PER_IP`,
default 5/hour), kept as a secondary spam guard alongside the wallet-balance check - state is a plain
dict guarded by a lock, resets on process restart, and does not work across multiple server instances.
