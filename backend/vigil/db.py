"""Database connection and initialization module for Vigil."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
from vigil.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATABASE_PATH = Path(os.environ.get("VIGIL_DB_PATH", PROJECT_ROOT / "data" / "vigil.db"))


def local_now() -> datetime:
    """Return an offset-aware local timestamp for human-friendly history views."""
    return datetime.now().astimezone()


def iso_now() -> str:
    return local_now().isoformat(timespec="seconds")


async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """FastAPI async dependency yielding a short-lived SQLite connection per request."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(DATABASE_PATH)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA busy_timeout = 5000;")
    await connection.execute("PRAGMA journal_mode = WAL;")
    await connection.execute("PRAGMA foreign_keys = ON;")
    try:
        yield connection
    finally:
        await connection.close()


async def initialize_database() -> None:
    """Initialize database tables, views, and indexes."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async for connection in get_db():
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS TrackingLogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                local_date TEXT NOT NULL,
                source TEXT NOT NULL CHECK (source IN ('browser', 'app')),
                application_name TEXT,
                url TEXT,
                domain TEXT,
                title TEXT,
                event_type TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_tracking_logs_local_date
                ON TrackingLogs (local_date, occurred_at DESC);

            CREATE TABLE IF NOT EXISTS PomodoroTasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'todo'
                    CHECK (status IN ('todo', 'in_progress', 'done')),
                estimate_pomodoros INTEGER NOT NULL DEFAULT 1,
                completed_pomodoros INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_completed_at TEXT
            );

            CREATE VIEW IF NOT EXISTS Tasks AS SELECT * FROM PomodoroTasks;

            CREATE TABLE IF NOT EXISTS PersistentTimerState (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                status TEXT NOT NULL DEFAULT 'idle',
                phase TEXT NOT NULL DEFAULT 'work',
                task_id INTEGER,
                remaining_seconds INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                ends_at TEXT,
                duration_at_start INTEGER NOT NULL DEFAULT 0,
                sessions_completed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )
        await connection.commit()
        logger.info("Database initialized successfully with WAL, busy_timeout=5000, and PersistentTimerState schema.")


async def cleanup_old_logs(retention_days: int = 30) -> None:
    """Purge tracking logs older than retention_days to keep database size bounded."""
    cutoff_date = (local_now().date() - timedelta(days=retention_days)).isoformat()
    async for db in get_db():
        cursor = await db.execute("DELETE FROM TrackingLogs WHERE local_date < ?", (cutoff_date,))
        deleted = cursor.rowcount
        await db.commit()
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} tracking logs older than {retention_days} days (cutoff: {cutoff_date}).")
