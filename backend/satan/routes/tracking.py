"""Activity tracking webhook API router."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.parse import urlparse

import aiosqlite
from fastapi import APIRouter, Depends, status
from satan.activity import SLEEP_EVENT_TYPE
from satan.db import get_db, local_now
from satan.models import TrackingEvent
from satan.timer import pause_running_timer, timer_lock

router = APIRouter(tags=["tracking"])

MAX_SLEEP_EVENT_AGE = timedelta(hours=24)


def resolve_sleep_time(client_time: datetime | None, now: datetime) -> datetime:
    """Trust the client's sleep timestamp unless it is missing, stale, or from the future."""
    if client_time is None:
        return now
    local_time = client_time.astimezone()
    if local_time > now:
        return now
    if now - local_time > MAX_SLEEP_EVENT_AGE:
        return now
    return local_time


@router.post("/track", status_code=status.HTTP_201_CREATED)
async def track_activity(
    payload: TrackingEvent, db: aiosqlite.Connection = Depends(get_db)
) -> dict[str, int]:
    """Store an activity event supplied by the local browser or app tracker."""
    domain: str | None = None
    if payload.url:
        try:
            domain = urlparse(payload.url).hostname
        except ValueError:
            domain = None
    now = local_now()
    is_sleep = payload.event_type == SLEEP_EVENT_TYPE
    occurred = resolve_sleep_time(payload.occurred_at, now) if is_sleep else now
    cursor = await db.execute(
        """
        INSERT INTO TrackingLogs
            (occurred_at, local_date, source, application_name, url, domain, title, event_type, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurred.isoformat(timespec="seconds"),
            occurred.date().isoformat(),
            payload.source,
            payload.application_name,
            payload.url,
            domain,
            payload.title,
            payload.event_type,
            json.dumps(payload.metadata, separators=(",", ":")),
        ),
    )
    await db.commit()
    log_id = cursor.lastrowid
    await cursor.close()

    if is_sleep:
        # Lid closed / display asleep: stop the Pomodoro at the moment it happened.
        async with timer_lock:
            await pause_running_timer(db, at=occurred, reason=SLEEP_EVENT_TYPE)

    return {"id": log_id}
