"""Focus Load (acute vs. chronic workload) API router."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, Query
from satan.activity import get_daily_totals, get_first_tracked_date
from satan.db import get_db, local_now
from satan.focus_load import DailyRecord, compute_focus_load, records_needed

router = APIRouter(tags=["focus-load"])


@router.get("/focus-load")
async def focus_load(
    days: int = Query(default=30, ge=7, le=180, description="Chart window: 30, 60 or 90 days"),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    today = local_now().date()
    record_days = records_needed(days)
    start = today - timedelta(days=record_days - 1)

    first_date = await get_first_tracked_date(db)
    days_tracked = (today - first_date).days + 1 if first_date else 0
    # Nothing exists before the first tracked day; don't scan or roll up empty history.
    totals = await get_daily_totals(db, max(start, first_date) if first_date else today, today)

    records = []
    for offset in range(record_days):
        day = (start + timedelta(days=offset)).isoformat()
        day_totals = totals.get(day, {})
        records.append(
            DailyRecord(
                date=day,
                focus_minutes=day_totals.get("focus_seconds", 0) / 60,
                laptop_minutes=day_totals.get("laptop_seconds", 0) / 60,
            )
        )

    result = compute_focus_load(records, days_tracked, history_days=days)
    result["rangeDays"] = days
    return result
