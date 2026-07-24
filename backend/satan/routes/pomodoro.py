"""Pomodoro timer control API router."""

from __future__ import annotations

from datetime import timedelta
from time import monotonic
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from satan.audio import announce
from satan.db import get_db, iso_now, local_now
from satan.models import PomodoroStart
from satan.routes.tasks import get_task_or_404
from satan.timer import (
    cancel_timer_job,
    save_timer_state,
    schedule_phase_completion,
    timer_lock,
    timer_snapshot,
    timer_state,
)

router = APIRouter(prefix="/pomodoro", tags=["pomodoro"])


@router.get("", response_model=dict[str, Any])
async def pomodoro_status() -> dict[str, Any]:
    return await timer_snapshot()


@router.post("/start", response_model=dict[str, Any])
async def start_pomodoro(
    payload: PomodoroStart, db: aiosqlite.Connection = Depends(get_db)
) -> dict[str, Any]:
    if payload.task_id is not None:
        await get_task_or_404(db, payload.task_id)

    async with timer_lock:
        if timer_state.status != "idle":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="A Pomodoro is already active"
            )
        timer_state.status = "running"
        timer_state.phase = "work"
        timer_state.task_id = payload.task_id
        timer_state.remaining_seconds = payload.duration_seconds
        timer_state.started_monotonic = monotonic()
        timer_state.started_at = local_now().isoformat(timespec="seconds")
        timer_state.duration_at_start = payload.duration_seconds
        timer_state.ends_at = (
            local_now() + timedelta(seconds=payload.duration_seconds)
        ).isoformat(timespec="seconds")
        await save_timer_state(db)
        schedule_phase_completion(payload.duration_seconds)

    if payload.task_id is not None:
        await db.execute(
            "UPDATE PomodoroTasks SET status = 'in_progress', updated_at = ? WHERE id = ?",
            (iso_now(), payload.task_id),
        )
        await db.commit()

    announce("Pomodoro started.")
    return await timer_snapshot()


@router.post("/pause", response_model=dict[str, Any])
async def pause_pomodoro(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    async with timer_lock:
        if timer_state.status != "running" or timer_state.started_monotonic is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="No running Pomodoro to pause"
            )
        elapsed = monotonic() - timer_state.started_monotonic
        timer_state.remaining_seconds = max(0, timer_state.remaining_seconds - int(elapsed))
        timer_state.status = "paused"
        timer_state.started_monotonic = None
        timer_state.started_at = None
        timer_state.duration_at_start = 0
        timer_state.ends_at = None
        cancel_timer_job()
        await save_timer_state(db)

    announce("Timer paused.")
    return await timer_snapshot()


@router.post("/resume", response_model=dict[str, Any])
async def resume_pomodoro(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    async with timer_lock:
        if timer_state.status != "paused":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="No paused Pomodoro to resume"
            )
        if timer_state.remaining_seconds <= 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The paused Pomodoro has no time remaining",
            )
        timer_state.status = "running"
        timer_state.started_monotonic = monotonic()
        timer_state.started_at = local_now().isoformat(timespec="seconds")
        timer_state.duration_at_start = timer_state.remaining_seconds
        timer_state.ends_at = (
            local_now() + timedelta(seconds=timer_state.remaining_seconds)
        ).isoformat(timespec="seconds")
        await save_timer_state(db)
        schedule_phase_completion(timer_state.remaining_seconds)

    announce("Timer resumed.")
    return await timer_snapshot()


@router.post("/stop", response_model=dict[str, Any])
async def stop_pomodoro(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    async with timer_lock:
        if timer_state.status == "idle":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="No active Pomodoro to stop"
            )
        cancel_timer_job()
        timer_state.status = "idle"
        timer_state.phase = "work"
        timer_state.task_id = None
        timer_state.remaining_seconds = 0
        timer_state.started_monotonic = None
        timer_state.started_at = None
        timer_state.duration_at_start = 0
        timer_state.ends_at = None
        await save_timer_state(db)

    announce("Pomodoro stopped.")
    return await timer_snapshot()
