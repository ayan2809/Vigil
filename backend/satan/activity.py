"""Shared activity aggregation: the single home of the gap-based active-time SQL.

Durations are computed at read time from raw ``TrackingLogs`` events with a ``LEAD()`` window
function (gap to the next event, capped at 900s). ``system_sleep`` events (lid close / display
sleep, emitted by the macOS tracker) act as terminators: they stay in the window so the last real
event before sleep is measured up to the sleep time, but they contribute no time themselves, so the
span between sleep and the next event is never counted.

Finalized past days are additionally persisted in ``DailyActivityRollup`` so history survives the
30-day raw-log retention purge (see ``cleanup_old_logs``).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import aiosqlite
from satan.db import local_now
from satan.logger import logger

DURATION_CAP_SECONDS = 900
DEFAULT_FOCUS_SECONDS = 1500
SLEEP_EVENT_TYPE = "system_sleep"

# Events excluded from laptop-time windows entirely.
_EVENT_FILTER = """event_type != 'pomodoro_completed'
              AND COALESCE(application_name, '') NOT IN ('loginwindow', 'ScreenSaverEngine')"""

# Per-event duration. Expects the columns `event_type`, `occurred_at`, `next_occurred_at`,
# `local_date`, and one bound parameter: today's local date.
_DURATION_EXPR = f"""CASE
                WHEN event_type = '{SLEEP_EVENT_TYPE}' THEN 0
                WHEN next_occurred_at IS NOT NULL THEN
                    MIN(MAX(0, CAST((strftime('%s', next_occurred_at) - strftime('%s', occurred_at)) AS INTEGER)), {DURATION_CAP_SECONDS})
                WHEN local_date = ? THEN
                    MIN(MAX(0, CAST((strftime('%s', 'now', 'localtime') - strftime('%s', occurred_at)) AS INTEGER)), {DURATION_CAP_SECONDS})
                ELSE 60
            END"""


async def get_app_durations(db: aiosqlite.Connection, date_str: str) -> list[aiosqlite.Row]:
    """Per (source, app, domain) active seconds for one local date."""
    query = f"""
    WITH EventWindow AS (
        SELECT
            local_date,
            event_type,
            source,
            COALESCE(application_name, CASE WHEN source = 'browser' THEN 'Arc' ELSE 'Unknown App' END) AS app_name,
            domain,
            occurred_at,
            LEAD(occurred_at) OVER (ORDER BY occurred_at ASC) AS next_occurred_at
        FROM TrackingLogs
        WHERE local_date = ? AND {_EVENT_FILTER}
    ),
    EventDurations AS (
        SELECT
            source,
            app_name,
            domain,
            {_DURATION_EXPR} AS duration
        FROM EventWindow
    )
    SELECT source, app_name, domain, SUM(duration) AS total_duration
    FROM EventDurations
    WHERE duration > 0
    GROUP BY source, app_name, domain;
    """
    cursor = await db.execute(query, (date_str, local_now().date().isoformat()))
    rows = await cursor.fetchall()
    await cursor.close()
    return list(rows)


async def get_daily_activity_records(
    db: aiosqlite.Connection, start: date, end: date
) -> dict[str, dict[str, int]]:
    """Live per-day totals computed from raw logs for ``start..end`` inclusive.

    Only dates with any laptop activity or completed Pomodoros appear in the result. Each value is
    ``{"event_count", "laptop_seconds", "focus_seconds"}``.
    """
    start_str, end_str = start.isoformat(), end.isoformat()
    query = f"""
    WITH ActivityEvents AS (
        SELECT
            local_date,
            event_type,
            occurred_at,
            LEAD(occurred_at) OVER (PARTITION BY local_date ORDER BY occurred_at ASC) AS next_occurred_at
        FROM TrackingLogs
        WHERE local_date BETWEEN ? AND ? AND {_EVENT_FILTER}
    ),
    ActivityDurations AS (
        SELECT
            local_date,
            {_DURATION_EXPR} AS duration
        FROM ActivityEvents
    )
    SELECT local_date, COUNT(*) AS event_count, SUM(duration) AS total_laptop_time
    FROM ActivityDurations
    WHERE duration > 0
    GROUP BY local_date;
    """
    cursor = await db.execute(query, (start_str, end_str, local_now().date().isoformat()))
    laptop_rows = await cursor.fetchall()
    await cursor.close()

    records: dict[str, dict[str, int]] = {
        row["local_date"]: {
            "event_count": row["event_count"],
            "laptop_seconds": row["total_laptop_time"],
            "focus_seconds": 0,
        }
        for row in laptop_rows
    }

    cursor = await db.execute(
        f"""
        SELECT local_date,
               SUM(COALESCE(CAST(json_extract(metadata_json, '$.duration_seconds') AS INTEGER), {DEFAULT_FOCUS_SECONDS})) AS total_focus_time
        FROM TrackingLogs
        WHERE local_date BETWEEN ? AND ? AND event_type = 'pomodoro_completed'
        GROUP BY local_date
        """,
        (start_str, end_str),
    )
    focus_rows = await cursor.fetchall()
    await cursor.close()

    for row in focus_rows:
        record = records.setdefault(
            row["local_date"], {"event_count": 0, "laptop_seconds": 0, "focus_seconds": 0}
        )
        record["focus_seconds"] = row["total_focus_time"]

    return records


async def _stored_rollups(
    db: aiosqlite.Connection, start: date, end: date
) -> dict[str, dict[str, int]]:
    cursor = await db.execute(
        """
        SELECT local_date, laptop_seconds, focus_seconds
        FROM DailyActivityRollup
        WHERE local_date BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return {
        row["local_date"]: {
            "laptop_seconds": row["laptop_seconds"],
            "focus_seconds": row["focus_seconds"],
        }
        for row in rows
    }


async def rollup_past_days(db: aiosqlite.Connection) -> int:
    """Persist totals for every finalized (before today) date in ``TrackingLogs`` lacking a rollup.

    Must run before ``cleanup_old_logs`` so days about to be purged are captured first.
    Returns the number of rollup rows written.
    """
    today = local_now().date()
    cursor = await db.execute(
        "SELECT MIN(local_date) AS first_date FROM TrackingLogs WHERE local_date < ?",
        (today.isoformat(),),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None or row["first_date"] is None:
        return 0
    return await _fill_missing_rollups(db, date.fromisoformat(row["first_date"]), today - timedelta(days=1))


async def _fill_missing_rollups(db: aiosqlite.Connection, start: date, end: date) -> int:
    if end < start:
        return 0
    stored = await _stored_rollups(db, start, end)
    span = (end - start).days + 1
    if len(stored) >= span:
        return 0
    live = await get_daily_activity_records(db, start, end)
    now_str = local_now().isoformat(timespec="seconds")
    written = 0
    for date_str, record in live.items():
        if date_str in stored:
            continue
        await db.execute(
            """
            INSERT OR IGNORE INTO DailyActivityRollup (local_date, laptop_seconds, focus_seconds, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (date_str, record["laptop_seconds"], record["focus_seconds"], now_str),
        )
        written += 1
    if written:
        await db.commit()
        logger.info(f"Rolled up {written} finalized day(s) into DailyActivityRollup.")
    return written


async def get_daily_totals(
    db: aiosqlite.Connection, start: date, end: date
) -> dict[str, dict[str, Any]]:
    """Per-day ``{"laptop_seconds", "focus_seconds"}`` for ``start..end`` inclusive.

    Finalized days come from ``DailyActivityRollup`` (filled from raw logs when missing); today is
    always computed live. Dates without any data are omitted.
    """
    today = local_now().date()
    totals: dict[str, dict[str, Any]] = {}

    past_end = min(end, today - timedelta(days=1))
    if past_end >= start:
        await _fill_missing_rollups(db, start, past_end)
        totals.update(await _stored_rollups(db, start, past_end))

    if start <= today <= end:
        live = await get_daily_activity_records(db, today, today)
        record = live.get(today.isoformat())
        if record is not None:
            totals[today.isoformat()] = {
                "laptop_seconds": record["laptop_seconds"],
                "focus_seconds": record["focus_seconds"],
            }
    return totals


async def get_first_tracked_date(db: aiosqlite.Connection) -> date | None:
    """Earliest date with any recorded data, from the rollup or the (retained) raw logs."""
    cursor = await db.execute(
        """
        SELECT MIN(first_date) AS first_date FROM (
            SELECT MIN(local_date) AS first_date FROM DailyActivityRollup
            UNION ALL
            SELECT MIN(local_date) AS first_date FROM TrackingLogs
        )
        """
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None or row["first_date"] is None:
        return None
    return date.fromisoformat(row["first_date"])
