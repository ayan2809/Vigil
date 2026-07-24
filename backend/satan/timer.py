"""Pomodoro timer state machine with persistence and thread safety."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

import aiosqlite
from satan.audio import announce
from satan.db import get_db, iso_now, local_now
from satan.logger import logger
from satan.models import DEFAULT_BREAK_SECONDS, DEFAULT_WORK_SECONDS, TimerState

timer_state = TimerState()
timer_lock = asyncio.Lock()
timer_completion_job: asyncio.Task[None] | None = None


async def save_timer_state(db: aiosqlite.Connection) -> None:
    """Persist current timer state to SQLite table PersistentTimerState."""
    now_str = iso_now()
    await db.execute(
        """
        INSERT INTO PersistentTimerState (
            id, status, phase, task_id, remaining_seconds, started_at, ends_at,
            duration_at_start, sessions_completed, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            phase = excluded.phase,
            task_id = excluded.task_id,
            remaining_seconds = excluded.remaining_seconds,
            started_at = excluded.started_at,
            ends_at = excluded.ends_at,
            duration_at_start = excluded.duration_at_start,
            sessions_completed = excluded.sessions_completed,
            updated_at = excluded.updated_at
        """,
        (
            timer_state.status,
            timer_state.phase,
            timer_state.task_id,
            timer_state.remaining_seconds,
            timer_state.started_at,
            timer_state.ends_at,
            timer_state.duration_at_start,
            timer_state.sessions_completed,
            now_str,
        ),
    )
    await db.commit()


async def load_persisted_timer_state() -> None:
    """Restore timer state from SQLite on startup."""
    async with timer_lock:
        async for db in get_db():
            cursor = await db.execute("SELECT * FROM PersistentTimerState WHERE id = 1")
            row = await cursor.fetchone()
            await cursor.close()

        if not row:
            logger.info("No persisted timer state found.")
            return

        status = row["status"]
        phase = row["phase"]
        task_id = row["task_id"]
        remaining_seconds = row["remaining_seconds"]
        started_at_str = row["started_at"]
        ends_at_str = row["ends_at"]
        duration_at_start = row["duration_at_start"]
        sessions_completed = row["sessions_completed"]

        timer_state.status = status
        timer_state.phase = phase
        timer_state.task_id = task_id
        timer_state.duration_at_start = duration_at_start
        timer_state.sessions_completed = sessions_completed
        timer_state.started_at = started_at_str
        timer_state.ends_at = ends_at_str

        if status == "running" and started_at_str and ends_at_str:
            try:
                ends_dt = datetime.fromisoformat(ends_at_str)
                now_dt = local_now()
                remaining = int((ends_dt - now_dt).total_seconds())

                if remaining > 0:
                    timer_state.remaining_seconds = remaining
                    timer_state.started_monotonic = monotonic()
                    schedule_phase_completion(remaining)
                    logger.info(f"Restored running timer ({phase} phase), {remaining}s remaining.")
                else:
                    logger.info(f"Persisted running timer expired while offline. Finishing phase.")
                    schedule_phase_completion(0)
            except Exception as exc:
                logger.error(f"Error parsing timer timestamps during recovery: {exc}")
                timer_state.status = "idle"
        elif status == "paused":
            timer_state.remaining_seconds = remaining_seconds
            logger.info(f"Restored paused timer ({phase} phase), {remaining_seconds}s remaining.")
        else:
            timer_state.status = "idle"
            timer_state.remaining_seconds = 0


async def timer_snapshot() -> dict[str, Any]:
    """Thread-safe snapshot of current timer state."""
    async with timer_lock:
        payload = asdict(timer_state)
        if timer_state.status == "running" and timer_state.started_monotonic is not None:
            elapsed = monotonic() - timer_state.started_monotonic
            payload["remaining_seconds"] = max(0, timer_state.remaining_seconds - int(elapsed))
        return payload


def cancel_timer_job() -> None:
    global timer_completion_job
    if timer_completion_job is not None and not timer_completion_job.done():
        timer_completion_job.cancel()
    timer_completion_job = None


def schedule_phase_completion(seconds: int) -> None:
    global timer_completion_job
    timer_completion_job = asyncio.create_task(finish_phase_after(seconds))


async def complete_task_session(db: aiosqlite.Connection, task_id: int) -> None:
    now = iso_now()
    await db.execute(
        """
        UPDATE PomodoroTasks
        SET completed_pomodoros = completed_pomodoros + 1,
            status = CASE
                WHEN completed_pomodoros + 1 >= estimate_pomodoros THEN 'done'
                ELSE 'in_progress'
            END,
            last_completed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (now, now, task_id),
    )
    await db.commit()


async def finish_phase_after(seconds: int) -> None:
    """Sleep once for a phase, then execute state transition."""
    global timer_completion_job
    try:
        if seconds > 0:
            await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return

    announcement: str
    async with timer_lock:
        if timer_state.status != "running":
            return

        timer_completion_job = None
        async for db in get_db():
            if timer_state.phase == "work":
                focus_seconds = timer_state.duration_at_start or DEFAULT_WORK_SECONDS
                if timer_state.task_id is not None:
                    await complete_task_session(db, timer_state.task_id)

                occurred = local_now()
                await db.execute(
                    """
                    INSERT INTO TrackingLogs
                        (occurred_at, local_date, source, application_name, url, domain, title, event_type, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        occurred.isoformat(timespec="seconds"),
                        occurred.date().isoformat(),
                        "app",
                        "Satan Focus Timer",
                        None,
                        None,
                        f"Pomodoro Work Session Completed (Task ID: {timer_state.task_id})",
                        "pomodoro_completed",
                        json.dumps({
                            "task_id": timer_state.task_id,
                            "duration_seconds": focus_seconds
                        }, separators=(",", ":")),
                    )
                )
                await db.commit()

                timer_state.sessions_completed += 1
                timer_state.phase = "break"
                timer_state.remaining_seconds = DEFAULT_BREAK_SECONDS
                timer_state.started_monotonic = monotonic()
                timer_state.started_at = local_now().isoformat(timespec="seconds")
                timer_state.duration_at_start = DEFAULT_BREAK_SECONDS
                timer_state.ends_at = (local_now() + timedelta(seconds=DEFAULT_BREAK_SECONDS)).isoformat(
                    timespec="seconds"
                )
                await save_timer_state(db)
                schedule_phase_completion(DEFAULT_BREAK_SECONDS)
                announcement = "Work interval complete. Take a break."
            else:
                timer_state.status = "idle"
                timer_state.phase = "work"
                timer_state.task_id = None
                timer_state.remaining_seconds = 0
                timer_state.started_monotonic = None
                timer_state.started_at = None
                timer_state.duration_at_start = 0
                timer_state.ends_at = None
                await save_timer_state(db)
                announcement = "Break complete. Your next Pomodoro is ready."

    announce(announcement)
