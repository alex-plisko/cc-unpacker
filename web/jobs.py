"""Job queue using in-memory dict + SQLite for persistence."""

import sqlite3
import json
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "jobs.db"
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                package TEXT,
                version TEXT,
                status TEXT DEFAULT 'pending',
                progress TEXT,
                files_json TEXT,
                error TEXT,
                is_open_source INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                package_name TEXT,
                version TEXT,
                is_open_source INTEGER DEFAULT 0,
                has_sourcemaps INTEGER DEFAULT 0,
                scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        """)
        # Migration: add is_open_source to existing jobs tables that lack it
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN is_open_source INTEGER DEFAULT 0")
        except Exception:
            pass  # column already exists
        conn.commit()


def create_job(job_id: str, package: str, version: str):
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO jobs (id, package, version, status, progress) VALUES (?, ?, ?, 'pending', 'Queued...')",
                (job_id, package, version)
            )
            conn.commit()


def update_job(job_id: str, status: str = None, progress: str = None,
               files_json: str = None, error: str = None, is_open_source: int = None):
    with _lock:
        fields = []
        values = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if progress is not None:
            fields.append("progress = ?")
            values.append(progress)
        if files_json is not None:
            fields.append("files_json = ?")
            values.append(files_json)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if is_open_source is not None:
            fields.append("is_open_source = ?")
            values.append(is_open_source)
        if not fields:
            return
        values.append(job_id)
        with _get_conn() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()


def get_job(job_id: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return dict(row)


def job_exists(job_id: str) -> bool:
    return get_job(job_id) is not None


def upsert_scan_result(package_name: str, version: str, is_open_source: bool,
                       has_sourcemaps: bool, notes: str = None):
    """Save a scan result to the DB."""
    with _lock:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO scan_results (package_name, version, is_open_source, has_sourcemaps, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (package_name, version, int(is_open_source), int(has_sourcemaps), notes)
            )
            conn.commit()
