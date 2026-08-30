import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from app.config import DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Best-effort ALTER TABLE for a column added after a table already
    existed on disk. There's no migration system here (schema changes are
    hand-edited CREATE TABLE IF NOT EXISTS statements) - this just keeps an
    existing local data/jobs.db from an older schema working."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    except sqlite3.OperationalError:
        pass


def init_db() -> None:
    conn = get_connection()
    with _lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                wallet_balance_vnd INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topups (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                amount_vnd INTEGER NOT NULL,
                note TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                engine TEXT NOT NULL,
                language TEXT,
                language_detected TEXT,
                status TEXT NOT NULL,
                stage_message TEXT,
                error TEXT,
                transcript_text TEXT,
                segments_json TEXT,
                price_vnd INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _add_column_if_missing(conn, "jobs", "user_id", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "jobs", "price_vnd", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "users", "free_trial_used", "INTEGER NOT NULL DEFAULT 0")
        conn.commit()


# ---- users ----------------------------------------------------------------


def create_user(email: str, password_hash: str, role: str = "user") -> str:
    user_id = uuid.uuid4().hex
    conn = get_connection()
    with _lock:
        conn.execute(
            """
            INSERT INTO users (id, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, email, password_hash, role, _now()),
        )
        conn.commit()
    return user_id


def get_user_by_email(email: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_user(user_id: str, **fields) -> None:
    if not fields:
        return
    columns = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]
    conn = get_connection()
    with _lock:
        conn.execute(f"UPDATE users SET {columns} WHERE id = ?", values)
        conn.commit()


def try_charge_wallet(user_id: str, amount_vnd: int) -> bool:
    """Atomically deduct amount_vnd if the user's balance can cover it,
    returning False (leaving the balance untouched) otherwise. Holds the
    same lock as every other write so concurrent job creations can't both
    pass the balance check before either deduction lands."""
    conn = get_connection()
    with _lock:
        row = conn.execute(
            "SELECT wallet_balance_vnd FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None or row["wallet_balance_vnd"] < amount_vnd:
            return False
        conn.execute(
            "UPDATE users SET wallet_balance_vnd = wallet_balance_vnd - ? WHERE id = ?",
            (amount_vnd, user_id),
        )
        conn.commit()
        return True


def adjust_wallet_balance(user_id: str, delta_vnd: int) -> None:
    """Atomically add (or, with a negative delta, subtract) from a user's
    wallet balance - expressed as a relative change rather than read-modify-
    write to stay correct under concurrent job completions."""
    conn = get_connection()
    with _lock:
        conn.execute(
            "UPDATE users SET wallet_balance_vnd = wallet_balance_vnd + ? WHERE id = ?",
            (delta_vnd, user_id),
        )
        conn.commit()


def try_use_free_trial(user_id: str) -> bool:
    """Atomically consume the user's one free first transcription, returning
    False if it was already used. Runs under the same write lock as every
    other mutation so two simultaneous "first" jobs can't both claim it."""
    conn = get_connection()
    with _lock:
        row = conn.execute(
            "SELECT free_trial_used FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None or row["free_trial_used"]:
            return False
        conn.execute("UPDATE users SET free_trial_used = 1 WHERE id = ?", (user_id,))
        conn.commit()
        return True


def restore_free_trial(user_id: str) -> None:
    """Give the free trial back after the job that consumed it failed - a
    user should only spend their one free try on a job that actually
    produced a transcript, same principle as the paid-job refund below."""
    conn = get_connection()
    with _lock:
        conn.execute("UPDATE users SET free_trial_used = 0 WHERE id = ?", (user_id,))
        conn.commit()


def delete_user(user_id: str) -> None:
    conn = get_connection()
    with _lock:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


# ---- topups (manual bank-transfer requests, approved/rejected by an admin) -


def create_topup(user_id: str, amount_vnd: int, note: str) -> str:
    topup_id = uuid.uuid4().hex
    now = _now()
    conn = get_connection()
    with _lock:
        conn.execute(
            """
            INSERT INTO topups (id, user_id, amount_vnd, note, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (topup_id, user_id, amount_vnd, note, now, now),
        )
        conn.commit()
    return topup_id


def get_topup(topup_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM topups WHERE id = ?", (topup_id,)).fetchone()
    return dict(row) if row else None


def list_topups_for_user(user_id: str, limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM topups WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_topups(status: str | None = None, limit: int = 100) -> list[dict]:
    """List top-up requests, optionally filtered by status, joined with the
    requesting user's email so the admin panel doesn't need a second lookup."""
    conn = get_connection()
    if status:
        rows = conn.execute(
            """
            SELECT topups.*, users.email AS user_email
            FROM topups JOIN users ON users.id = topups.user_id
            WHERE topups.status = ?
            ORDER BY topups.created_at ASC LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT topups.*, users.email AS user_email
            FROM topups JOIN users ON users.id = topups.user_id
            ORDER BY topups.created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_topup(topup_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    columns = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [topup_id]
    conn = get_connection()
    with _lock:
        conn.execute(f"UPDATE topups SET {columns} WHERE id = ?", values)
        conn.commit()


# ---- jobs -------------------------------------------------------------------


def create_job(
    user_id: str,
    source_type: str,
    source_ref: str,
    language: str | None,
    price_vnd: int,
    engine: str = "openai",
) -> str:
    job_id = uuid.uuid4().hex
    now = _now()
    conn = get_connection()
    with _lock:
        conn.execute(
            """
            INSERT INTO jobs (id, user_id, source_type, source_ref, engine, language,
                               status, stage_message, price_vnd, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'queued', 'Queued', ?, ?, ?)
            """,
            (job_id, user_id, source_type, source_ref, engine, language, price_vnd, now, now),
        )
        conn.commit()
    return job_id


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    columns = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    conn = get_connection()
    with _lock:
        conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("segments_json"):
        d["segments"] = json.loads(d["segments_json"])
    else:
        d["segments"] = None
    return d


def get_job(job_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_jobs_for_user(user_id: str, limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]
