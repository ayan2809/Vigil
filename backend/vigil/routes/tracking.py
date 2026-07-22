"""Activity tracking webhook API router."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import aiosqlite
from fastapi import APIRouter, Depends, status
from vigil.db import get_db, local_now
from vigil.models import TrackingEvent

router = APIRouter(tags=["tracking"])


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
    occurred = local_now()
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
    return {"id": log_id}
