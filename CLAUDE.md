# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

kicban is a FastAPI web app: users register/log in, top up a wallet via manual bank transfer (scan a
VietQR code, an admin confirms and credits it - see "Manual bank-transfer top-up" below), then paste a
video link (TikTok/Facebook/direct URL) or upload a video/audio file to get speech transcribed to text
via the OpenAI API. Each transcription job deducts a price tiered by media duration from the user's
wallet (see "Wallet & pricing" below), refunded automatically if the job fails. A brand-new account's
first job is free (short videos only - see "Free trial"). There's an admin panel (`/admin`) to
approve/reject top-up requests, view users/jobs, manually adjust wallet balances, and lock/delete
accounts.

**No payment gateway (VNPay, MoMo, PayOS, ...) is integrated, and this was a deliberate choice, not an
oversight**: every one of them requires identity/business-verified merchant onboarding before issuing
API credentials (an AML/KYC legal requirement, not something any provider can skip), which blocked
getting the app usable quickly. A VNPay integration (`vnpay.py`, HMAC-SHA512 signed URLs + IPN webhook)
was built and verified working end-to-end in an earlier pass of this project, then deleted once VNPay's
merchant sandbox registration turned out to be stuck in an identity-verification flow with no clear
self-service path (a PayOS attempt hit a similar dead end). If a payment gateway is wanted again later,
that VNPay algorithm write-up is still useful reference (see git history for `vnpay.py` /
`tests/test_vnpay.py`), but don't assume it's what the user wants without asking - the manual flow was
a deliberate fallback, not a stopgap to silently replace.

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
uv run pytest tests/test_auth.py -v        # run a single test file
uv run pytest tests/test_auth.py::test_hash_password_verifies_correct_password  # run a single test
docker build -t kicban .                   # build production image
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... -e SECRET_KEY=... kicban
```

System requirements: `ffmpeg`/`ffprobe` on PATH (audio extraction/probing, and now also duration-based
price quoting for uploads - see "Wallet & pricing"). `OPENAI_API_KEY` is mandatory now (no local
fallback). `SECRET_KEY` must be a long random value in production - it signs session cookies, so a
leaked/default value lets anyone forge a login session.

## Architecture

**Request flow**: `routes/pages.py` serves server-rendered pages (`/`, `/login`, `/register`, `/admin`)
via Jinja2 templates; `routes/api.py` exposes `/api/jobs` (create by URL or upload, list, get status,
download `.txt`/`.srt`) - all gated behind login; `routes/auth.py` exposes `/api/auth/*`
(register/login/logout/me); `routes/wallet.py` exposes `/api/wallet/*` (create a top-up request + get
its VietQR code, list the current user's own top-up history); `routes/admin.py` exposes `/api/admin/*`
(admin-only user management, plus listing/approving/rejecting top-up requests). Job creation is not
instant - it synchronously determines the job's price before responding (see "Wallet & pricing") - but
still returns well before the media is fetched/transcribed: a 202 with a `job_id` and the `price_vnd`
that was actually charged, and the frontend polls `GET /api/jobs/{id}` for status.

**Auth** (`auth.py`): passwords are hashed with `bcrypt`. Sessions are a single signed cookie
(`itsdangerous.URLSafeTimedSerializer`, `SECRET_KEY`-keyed, `SESSION_MAX_AGE_SECONDS` = 30 days) -
there is no server-side session table, the cookie itself carries `{"user_id": ...}` and is
self-verifying, so logout is just clearing the cookie. `get_current_user` additionally re-checks
`is_locked` on every request against the DB (not baked into the cookie), so an admin lock takes effect
immediately without waiting for the session to expire. `require_user`/`require_admin` are FastAPI
`Depends()` dependencies; a locked or missing session surfaces as a plain 401 from `require_user`
(not a distinct "you're locked" message) to avoid leaking account-existence info.

`db.create_user` does its email-uniqueness check and insert as one operation under the write lock,
returning `None` on a duplicate instead of raising - `routes/auth.py`'s pre-check (`get_user_by_email`)
handles the common case cheaply, but the atomic check-and-insert is what actually closes the race where
two near-simultaneous registrations for the same email (e.g. a double submit) could both pass that
pre-check before either insert landed, which used to crash with an unhandled `sqlite3.IntegrityError`.

**Admin bootstrap**: there's no "create admin" UI or CLI - `ADMIN_EMAILS` (comma-separated env var) is
checked on both register and login; a matching email is promoted to `role="admin"` on the spot. This
is the only way to create the first admin account. On Render this means setting `ADMIN_EMAILS` in the
service's Environment tab, then either registering fresh with that email or logging out and back in on
an existing account (login re-checks and promotes on every sign-in).

**Wallet & pricing** (`pricing.py`): price is **tiered by media duration**, not a flat amount - `TIERS`
is a hardcoded list of `(upper_bound_seconds, price_vnd)` pairs (≤2 min = 2,000đ, 2–5 min = 4,000đ,
5–8 min = 6,000đ, 8–15 min = 10,000đ, 15–30 min = 18,000đ, 30–60 min = 28,000đ, 60–120 min = 50,000đ -
the last bound matches `MAX_DURATION_SECONDS`). This replaced an earlier flat `PRICE_PER_JOB_VND`:
Whisper's real cost scales with audio length (~$0.006/min, roughly 150đ/min), so one flat price either
overcharged short clips or lost money on long ones (a 2-hour video costs ~18,000đ to transcribe but a
flat 5,000đ charge wouldn't cover it). Each tier is priced well above its own worst-case cost, so no
tier can lose money even at its upper bound. Changing the price table means editing `TIERS` in code and
redeploying - it is deliberately not an env var, since it's a whole table rather than a single number.

`routes/api.py` determines the price **before** charging, which is a real behavior change worth
knowing: for a URL job it calls `media.probe_url` (a cheap yt-dlp metadata fetch, no download, retrying
like `download_via_ytdlp` does - see "Retry on download") to get the duration synchronously inside the
request handler - this makes job creation noticeably slower than a bare DB write (a real network
round-trip to TikTok/Facebook/etc.), a deliberate trade for accurate upfront pricing. For an upload it
runs `audio.probe` (ffprobe) on the already-saved file before charging.

If the probe still can't determine a URL job's duration after retrying, `create_url_job` does **not**
guess and charge blind - it calls `media.download_media` to fetch the file right there in the request
(no OpenAI cost yet, only server bandwidth/time), then runs `audio.probe` (ffprobe) on the downloaded
file to get the *real* duration before charging anything. This avoids the alternative of charging the
highest tier as a blind estimate, which could wrongly reject a user who has enough balance for the
video's real (lower) price but not for the pessimistic estimate. The downloaded path is saved as
`jobs.prefetched_path`; `jobs.py`'s `_run_job` checks for it first and, if present, skips fetching the
media again. This pre-fetch path is the slow one (a full download inside the request/response cycle)
but is now rare in practice since retries already resolve most probe failures. `pricing.price_for_duration_seconds(None)`
falling back to the highest tier only still applies if this download itself fails in a way that isn't a
clean `MediaError` (defensive - shouldn't normally happen) - and `jobs.py`'s `_reconcile_price` (called
after the pipeline's own post-download duration re-check) exists as a last-resort correction, refunding
the difference if a job ever ends up overcharged this way. Charging conservatively high and refunding
down beats trying to collect more from the wallet mid-job if an estimate turns out wrong -
`_reconcile_price` therefore only ever refunds, never charges more. `db.try_charge_wallet` does the
balance-check-and-deduct as one operation under `db.py`'s existing write lock, closing the race where
two concurrent job submissions could both pass a balance check before either deduction lands. `jobs.py`'s
`_refund` refunds `job["price_vnd"]` back to the wallet automatically on any failure path
(`MediaError`/`AudioError` or an unhandled exception) - so a user is only ever charged for a job that
actually produced a transcript. `_charge`'s `HTTPException` on insufficient balance uses a **structured
`detail`** (`{"message": ..., "duration_seconds": ..., "price_vnd": ...}`) rather than a plain string, so
the frontend can show what duration the rejected price was actually based on instead of just the amount
- `app.js` checks `typeof detail === "object"` to handle this alongside the plain-string details other
endpoints still use.

**Free trial**: a brand-new account gets one free transcription (`users.free_trial_used`, consumed
atomically by `db.try_use_free_trial` under the write lock so two simultaneous "first" jobs can't both
claim it), capped to videos ≤ `pricing.FREE_TRIAL_MAX_SECONDS` (10 min) so it can't be used to get a
long - and therefore costly to us - job for free; a job whose duration is unknown at charge time is
never treated as free-trial-eligible for the same reason. If that free job fails, `jobs.py`'s `_refund`
calls `db.restore_free_trial` to give the trial back rather than burning it on a job that produced
nothing, mirroring the paid-refund policy above. `/api/auth/me` exposes `free_trial_available` so the
frontend can show a banner ("index.html"'s `#free-trial-banner`).

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

**Job pipeline** (`jobs.py` → `media.py` → `audio.py` → `transcribe.py`, state in `db.py`): jobs go
through one `ThreadPoolExecutor` (`_job_pool`, 3 workers) - there's no GPU-bound local queue to
serialize around now that faster-whisper is gone. `_run_job` drives fetch media (`media.fetch_url` for
URLs, or the already-saved upload path) → `audio.normalize_to_wav` (ffmpeg, extracts mono 16kHz PCM) →
re-check duration against `MAX_DURATION_SECONDS` → `_reconcile_price` (see "Wallet & pricing") →
`transcribe.get_transcriber()` (always `OpenAITranscriber`) → write transcript/segments/status back via
`db.update_job`, refunding/restoring the free trial on any failure (see "Wallet & pricing" and "Free
trial" above). Errors are split into two tiers: known `MediaError`/`AudioError` write their message
straight to the job (user-facing); anything else is logged with `exc_info` and a generic message is
stored instead, so internals never leak to the client.

**Media fetch** (`media.py`): `probe_url` (yt-dlp, `skip_download`) is called first from `routes/api.py`
to quote a price before charging (see "Wallet & pricing"), and that result is persisted to
`jobs.duration_seconds` so `fetch_url` doesn't have to probe the same URL again - it accepts a
`known_duration` and only falls back to probing itself when that's `None` (duration wasn't determined
up front - in practice this now only happens for a job created outside the normal route flow, since
the route itself resolves an unknown duration by pre-fetching, see "Wallet & pricing"). `probe_url`
itself retries up to `_MAX_YTDLP_ATTEMPTS` times like `download_via_ytdlp` does (see "Retry on
download") - a probe hits the same flaky bot-challenge as a real download. `download_media` is
`fetch_url`'s download-only half (try `download_via_ytdlp`, fall back to `download_direct_url`) split
out so `routes/api.py` can call it directly for the pre-fetch case without re-probing a URL it already
knows can't be probed. A probe/download failure (after retries) is *not* treated as "unsupported,"
since that used to cause a broken fallback that downloaded raw HTML as if it were a media file. In
`fetch_url`, if that fails, `_is_known_site` checks whether a non-generic yt-dlp extractor
recognizes the URL - if so the yt-dlp error is re-raised as-is (real failure, not an unsupported link),
otherwise it falls back to `download_direct_url` (plain `httpx` GET, only accepted if the response
`Content-Type` is video/audio/octet-stream). This distinction matters: don't collapse these two failure
paths back together. **YouTube URLs never reach this module** in the current build - they're rejected
earlier in `routes/api.py` with a "temporarily unsupported" message, so the YouTube-specific code below
is dead in production but intentionally not deleted.

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
obtain from a datacenter IP without a separate token-provider service. Verified in practice that this
mitigation is *insufficient on its own* on a datacenter IP: extraction succeeds but the actual
format/media URL still gets rejected with "Requested format is not available" once YouTube enforces PO
Token on the fallback format too - confirmed both with and without real YouTube cookies. A real fix
needs a PO token provider (e.g. `bgutil-ytdlp-pot-provider`), which is nontrivial to deploy alongside
this app (needs a Node.js sidecar/service - either bundled into the Docker image, which risks
native-dependency breakage from the `canvas` npm package, or run as a second paid Render service) and
has not been added; that tradeoff (extra cost + complexity vs. YouTube support) is a product decision,
not a technical one, so don't just wire it in - check with the user first.

**Retry on download** (`download_via_ytdlp` and `probe_url`): TikTok's (and sometimes YouTube's) bot
challenge is flaky rather than a hard block — the same URL and cookies can fail on one attempt and
succeed on the next. Both functions retry up to `_MAX_YTDLP_ATTEMPTS` (3) times with a
`_RETRY_DELAY_SECONDS` (3s) pause; `download_via_ytdlp` gives up by raising the generic "Could not
access this video" `MediaError`, `probe_url` gives up by returning `None` (see "Media fetch").

**Transcription** (`transcribe.py`): only `OpenAITranscriber` remains, implementing the `Transcriber`
protocol (`transcribe(wav_path, language) -> TranscriptionResult`); `get_transcriber()` takes no
argument now. It only requests `verbose_json` (needed for per-segment timestamps / `.srt` export) from
models in `_VERBOSE_JSON_MODELS` (currently just `whisper-1`) — other models (e.g. `gpt-4o-transcribe`)
only support plain `json` and come back as one synthetic zero-timestamp segment.

**Storage**: SQLite at `data/jobs.db` (single connection, `check_same_thread=False`, guarded by a
module-level `threading.Lock` in `db.py` - every write goes through that lock, including
`try_charge_wallet`'s check-and-deduct and `try_use_free_trial`'s check-and-set, which is why they're
race-safe). Three tables: `users` (email/password_hash/role/wallet_balance_vnd/is_locked/
free_trial_used), `topups` (manual top-up requests, keyed by a unique `note` - the bank transfer
content string - with `status` pending/approved/rejected), and `jobs` (user_id/price_vnd/duration_seconds/
prefetched_path plus the usual status/transcript/segments fields; `duration_seconds` is the
probed/measured duration used to price the job, cached here so `fetch_url` doesn't re-probe a URL it
already probed for pricing; `prefetched_path` is set only when `routes/api.py` had to download the
media itself to measure an unprobeable URL's duration before charging, so `jobs.py` knows to reuse that
file instead of fetching it again).
There are no migrations - schema changes are hand-edited
`CREATE TABLE IF NOT EXISTS` statements, plus a small `_add_column_if_missing` helper (best-effort
`ALTER TABLE`, swallows "duplicate column") used when a column was added to a table that already
existed on someone's disk; this only matters for a persisted local `data/jobs.db` since Render's
free-tier disk is ephemeral and gets a fresh schema on every redeploy anyway. **Once real users have
real money in their wallets, losing this file on redeploy is a real problem** - a persistent disk
becomes necessary at that point, not optional. Working files live under `data/` (`uploads/`,
`downloads/`, `audio/`) and are named by `job_id`.

**Config** (`config.py`): all environment-derived settings live here as module-level globals, loaded
once via `load_dotenv()` at import time. `OPENAI_ENABLED`/`MANUAL_TOPUP_ENABLED` gate whether those
features work at all, derived from whether their required env vars are set rather than a separate flag.
Pricing is *not* here - it's hardcoded in `pricing.py` (see "Wallet & pricing").

**Rate limiting** (`ratelimit.py`): in-memory per-IP sliding window (`MAX_JOBS_PER_HOUR_PER_IP`,
default 5/hour), kept as a secondary spam guard alongside the wallet-balance check - state is a plain
dict guarded by a lock, resets on process restart, and does not work across multiple server instances.

**Frontend/UI** (`static/css/style.css`, `templates/base.html`): a glassmorphism/gradient redesign -
translucent `backdrop-filter` panels, an animated "aurora" background (three blurred gradient blobs
that slowly drift via CSS keyframes, defined in `base.html`/`style.css` and present on every page), a
pill-style tab switcher, and fade-in transitions on newly-shown panels. Element IDs referenced by
`app.js`/`admin.js`/`login.js`/`register.js` were deliberately kept unchanged during this redesign, so
JS logic and markup structure/IDs are decoupled from styling - restyling further should keep doing the
same (check which IDs a script depends on before renaming or restructuring markup around them). Native
`<select>` dropdown popups don't inherit the page's translucent theming (they render as a solid,
browser-controlled popup), so `<option>` needs its own explicit `background-color`/`color` per
color-scheme in `style.css` or its text can render illegibly (near-invisible light text on the browser's
default white popup) - this was hit and fixed once already, don't reintroduce it by removing those
rules. The job history list (`app.js`'s `loadHistory`) renders each row as **two separate spans**,
`.history-source` (the URL/filename, which truncates with an ellipsis on overflow) and `.history-meta`
(duration + status, fixed-width, never truncated) - they used to be one span, which meant a long TikTok
URL (common, since shared links carry tracking query params) could fill the whole row and silently hide
the status/duration text that came after it in the same string. Keep them as separate elements if this
row is restyled further.
