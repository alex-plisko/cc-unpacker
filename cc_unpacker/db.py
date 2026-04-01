"""SQLite database layer for cc-unpacker analysis history."""

import sqlite3
import os
from pathlib import Path
from datetime import datetime
from typing import Optional


DB_DIR = Path.home() / ".cc-unpacker"
DB_PATH = DB_DIR / "analyses.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection, creating the DB if needed."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT,
            version TEXT,
            analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            files_count INTEGER,
            summary TEXT,
            full_report TEXT
        )
    """)
    conn.commit()


def save_analysis(
    package_name: str,
    version: str,
    files_count: int,
    summary: str,
    full_report: str,
) -> int:
    """Save an analysis result. Returns the new row id."""
    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO analyses (package_name, version, files_count, summary, full_report)
        VALUES (?, ?, ?, ?, ?)
        """,
        (package_name, version, files_count, summary, full_report),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_analyses(limit: int = 50) -> list[sqlite3.Row]:
    """Return recent analyses, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, package_name, version, analyzed_at, files_count, summary FROM analyses ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def get_analysis(analysis_id: int) -> Optional[sqlite3.Row]:
    """Fetch a single analysis by id."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
    ).fetchone()
    conn.close()
    return row
