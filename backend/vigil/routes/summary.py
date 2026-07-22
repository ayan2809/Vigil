"""Activity summary and active time aggregation API router."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends
from vigil.db import get_db, local_now

router = APIRouter(tags=["summary"])


@router.get("/active-time-summary")
async def active_time_summary(
    date: str | None = None, db: aiosqlite.Connection = Depends(get_db)
) -> dict[str, Any]:
    selected_date = date or local_now().date().isoformat()
    today_str = local_now().date().isoformat()

    query = """
    WITH EventWindow AS (
        SELECT
            source,
            COALESCE(application_name, 'Unknown App') AS app_name,
            domain,
            occurred_at,
            LEAD(occurred_at) OVER (ORDER BY occurred_at ASC) AS next_occurred_at
        FROM TrackingLogs
        WHERE local_date = ? AND event_type != 'pomodoro_completed'
    ),
    EventDurations AS (
        SELECT
            source,
            app_name,
            domain,
            CASE
                WHEN next_occurred_at IS NOT NULL THEN
                    MIN(MAX(0, CAST((strftime('%s', next_occurred_at) - strftime('%s', occurred_at)) AS INTEGER)), 900)
                WHEN ? = ? THEN
                    MIN(MAX(0, CAST((strftime('%s', 'now', 'localtime') - strftime('%s', occurred_at)) AS INTEGER)), 900)
                ELSE 60
            END AS duration
        FROM EventWindow
    )
    SELECT
        source,
        app_name,
        domain,
        SUM(duration) AS total_duration
    FROM EventDurations
    WHERE duration > 0
    GROUP BY source, app_name, domain;
    """

    cursor = await db.execute(query, (selected_date, selected_date, today_str))
    rows = await cursor.fetchall()
    await cursor.close()

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
    today_str = today.isoformat()
    start_date = today - timedelta(days=safe_days - 1)
    start_date_str = start_date.isoformat()

    query = """
    WITH ActivityEvents AS (
        SELECT
            local_date,
            occurred_at,
            LEAD(occurred_at) OVER (PARTITION BY local_date ORDER BY occurred_at ASC) AS next_occurred_at
        FROM TrackingLogs
        WHERE local_date BETWEEN ? AND ? AND event_type != 'pomodoro_completed'
    ),
    ActivityDurations AS (
        SELECT
            local_date,
            CASE
                WHEN next_occurred_at IS NOT NULL THEN
                    MIN(MAX(0, CAST((strftime('%s', next_occurred_at) - strftime('%s', occurred_at)) AS INTEGER)), 900)
                WHEN local_date = ? THEN
                    MIN(MAX(0, CAST((strftime('%s', 'now', 'localtime') - strftime('%s', occurred_at)) AS INTEGER)), 900)
                ELSE 60
            END AS duration
        FROM ActivityEvents
    ),
    DailyLaptopTime AS (
        SELECT local_date, COUNT(*) AS event_count, SUM(duration) AS total_laptop_time
        FROM ActivityDurations
        WHERE duration > 0
        GROUP BY local_date
    ),
    DailyFocusTime AS (
        SELECT
            local_date,
            SUM(
                COALESCE(
                    CAST(json_extract(metadata_json, '$.duration_seconds') AS INTEGER),
                    1500
                )
            ) AS total_focus_time
        FROM TrackingLogs
        WHERE local_date BETWEEN ? AND ? AND event_type = 'pomodoro_completed'
        GROUP BY local_date
    )
    SELECT
        l.local_date AS date,
        l.event_count,
        l.total_laptop_time,
        COALESCE(f.total_focus_time, 0) AS total_focus_time
    FROM DailyLaptopTime l
    LEFT JOIN DailyFocusTime f ON l.local_date = f.local_date;
    """

    cursor = await db.execute(
        query, (start_date_str, today_str, today_str, start_date_str, today_str)
    )
    rows = await cursor.fetchall()
    await cursor.close()

    summary_map = {
        row["date"]: {
            "event_count": row["event_count"],
            "total_laptop_time_seconds": row["total_laptop_time"],
            "total_focus_time_seconds": row["total_focus_time"],
        }
        for row in rows
    }

    # Handle dates with only focus events or zero events
    cursor = await db.execute(
        """
        SELECT local_date, SUM(COALESCE(CAST(json_extract(metadata_json, '$.duration_seconds') AS INTEGER), 1500)) AS total_focus_time
        FROM TrackingLogs
        WHERE local_date BETWEEN ? AND ? AND event_type = 'pomodoro_completed'
        GROUP BY local_date
        """,
        (start_date_str, today_str),
    )
    focus_rows = await cursor.fetchall()
    await cursor.close()

    for frow in focus_rows:
        d = frow["local_date"]
        if d not in summary_map:
            summary_map[d] = {
                "event_count": 0,
                "total_laptop_time_seconds": 0,
                "total_focus_time_seconds": frow["total_focus_time"],
            }
        else:
            summary_map[d]["total_focus_time_seconds"] = frow["total_focus_time"]

    result = []
    for offset in range(safe_days):
        current = start_date + timedelta(days=offset)
        cur_str = current.isoformat()
        day_data = summary_map.get(
            cur_str,
            {
                "event_count": 0,
                "total_laptop_time_seconds": 0,
                "total_focus_time_seconds": 0,
            },
        )
        result.append({
            "date": cur_str,
            "event_count": day_data["event_count"],
            "total_laptop_time_seconds": day_data["total_laptop_time_seconds"],
            "total_focus_time_seconds": day_data["total_focus_time_seconds"],
        })

    return {"days": result}
