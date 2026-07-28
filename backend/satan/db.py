"""Database connection and initialization module for Vigil."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
from satan.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = PROJECT_ROOT / "data" / "satan.db"
_OLD_DB = PROJECT_ROOT / "data" / "vigil.db"
if not _DEFAULT_DB.exists() and _OLD_DB.exists():
    try:
        import shutil
        shutil.copyfile(_OLD_DB, _DEFAULT_DB)
    except Exception:
        pass

DATABASE_PATH = Path(os.environ.get("SATAN_DB_PATH", _DEFAULT_DB))


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


DEFAULT_MONTHLY_GOAL = "Set your goal for the month here."
DEFAULT_MONTHLY_GOALS = ["Set your goal for the month here."]
import json
DEFAULT_MONTHLY_GOALS_JSON = json.dumps(DEFAULT_MONTHLY_GOALS)
DEFAULT_CORE_VALUES = [
    "20 min emotional audit (written, action-oriented)",
    "Meaningful connection with Mom (presence > venting)",
    "AI used as tool, never as emotional authority",
    "Screen time < 2 hrs with penalties if crossed",
    "No half-attachments or emotional crutches while building goals",
    "Ask who should I be today",
    "Keep those promises to yourself",
    "Detach emotions from end goals; attach to small wins over the day",
    "Ban 'At Least'",
    "Track Actions, Ignore Intentions",
    "Kill the 'Right Time'",
    "Apply the 'Friend Test'",
    "Past wounds don't get to write the rules for future relationships",
]
DEFAULT_CORE_VALUES_JSON = json.dumps(DEFAULT_CORE_VALUES)


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

            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                pomodoro_duration_minutes INTEGER NOT NULL DEFAULT 25,
                sleep_time TEXT NOT NULL DEFAULT '23:00',
                reflection_email TEXT,
                monthly_goal TEXT,
                monthly_goals TEXT,
                core_values TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS email_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_date TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                is_sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                sent_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_email_outbox_sent ON email_outbox (is_sent, target_date);
            """
        )

        # Migration check for existing user_settings table
        cursor = await connection.execute("PRAGMA table_info(user_settings)")
        columns = [row["name"] for row in await cursor.fetchall()]
        await cursor.close()

        if "monthly_goal" not in columns:
            await connection.execute("ALTER TABLE user_settings ADD COLUMN monthly_goal TEXT")
        if "monthly_goals" not in columns:
            await connection.execute("ALTER TABLE user_settings ADD COLUMN monthly_goals TEXT")
        if "core_values" not in columns:
            await connection.execute("ALTER TABLE user_settings ADD COLUMN core_values TEXT")

        # Seed initial default row id=1
        await connection.execute(
            """
            INSERT INTO user_settings (id, pomodoro_duration_minutes, sleep_time, reflection_email, monthly_goal, monthly_goals, core_values, updated_at)
            VALUES (1, 25, '23:00', NULL, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                monthly_goal = COALESCE(user_settings.monthly_goal, excluded.monthly_goal),
                monthly_goals = COALESCE(user_settings.monthly_goals, excluded.monthly_goals),
                core_values = COALESCE(user_settings.core_values, excluded.core_values);
            """,
            (DEFAULT_MONTHLY_GOAL, DEFAULT_MONTHLY_GOALS_JSON, DEFAULT_CORE_VALUES_JSON),
        )

        await connection.commit()
        logger.info("Database initialized successfully with user_settings (monthly_goal & core_values), email_outbox, and PersistentTimerState schemas.")


async def cleanup_old_logs(retention_days: int = 30) -> None:
    """Purge tracking logs older than retention_days to keep database size bounded."""
    cutoff_date = (local_now().date() - timedelta(days=retention_days)).isoformat()
    async for db in get_db():
        cursor = await db.execute("DELETE FROM TrackingLogs WHERE local_date < ?", (cutoff_date,))
        deleted = cursor.rowcount
        await db.commit()
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} tracking logs older than {retention_days} days (cutoff: {cutoff_date}).")
