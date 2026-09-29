"""Activity summary and active time aggregation API router."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends
from satan.activity import get_app_durations, get_daily_activity_records
from satan.db import get_db, local_now

router = APIRouter(tags=["summary"])


@router.get("/active-time-summary")
async def active_time_summary(
    date: str | None = None, db: aiosqlite.Connection = Depends(get_db)
) -> dict[str, Any]:
    selected_date = date or local_now().date().isoformat()
    rows = await get_app_durations(db, selected_date)

    if not rows:
        return {"totalSeconds": 0, "apps": []}

    apps: dict[str, dict[str, Any]] = {}
    total_seconds = 0

    for row in rows:
        source = row["source"]
        app_name = row["app_name"]
        domain = row["domain"]
        duration = row["total_duration"]

        total_seconds += duration

        if app_name not in apps:
            apps[app_name] = {
                "name": app_name,
                "source": source,
                "seconds": 0,
                "domains": {},
            }

        apps[app_name]["seconds"] += duration

        if source == "browser" and domain:
            apps[app_name]["domains"][domain] = (
                apps[app_name]["domains"].get(domain, 0) + duration
            )

    apps_list = []
    for app_name, app_data in apps.items():
        domains_list = [
            {"domain": dom, "seconds": sec}
            for dom, sec in sorted(
                app_data["domains"].items(), key=lambda item: item[1], reverse=True
            )
        ]
        apps_list.append({
            "name": app_name,
            "source": app_data["source"],
            "seconds": app_data["seconds"],
            "domains": domains_list,
        })

    apps_list.sort(key=lambda item: item["seconds"], reverse=True)
    return {"totalSeconds": total_seconds, "apps": apps_list}


@router.get("/activity/summary")
async def activity_summary(
    days: int = 28, db: aiosqlite.Connection = Depends(get_db)
) -> dict[str, Any]:
    safe_days = min(max(days, 1), 365)
    today = local_now().date()
    start_date = today - timedelta(days=safe_days - 1)

    records = await get_daily_activity_records(db, start_date, today)
    empty = {"event_count": 0, "laptop_seconds": 0, "focus_seconds": 0}

    result = []
    for offset in range(safe_days):
        cur_str = (start_date + timedelta(days=offset)).isoformat()
        day_data = records.get(cur_str, empty)
        result.append({
            "date": cur_str,
            "event_count": day_data["event_count"],
            "total_laptop_time_seconds": day_data["laptop_seconds"],
            "total_focus_time_seconds": day_data["focus_seconds"],
        })

    return {"days": result}
