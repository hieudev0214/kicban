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


def init_db() -> None:
    conn = get_connection()
    with _lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def create_job(source_type: str, source_ref: str, engine: str, language: str | None) -> str:
    job_id = uuid.uuid4().hex
    now = _now()
    conn = get_connection()
    with _lock:
        conn.execute(
            """
            INSERT INTO jobs (id, source_type, source_ref, engine, language, status,
                               stage_message, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'queued', 'Queued', ?, ?)
            """,
            (job_id, source_type, source_ref, engine, language, now, now),
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
