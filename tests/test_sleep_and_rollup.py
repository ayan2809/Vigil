"""Integration tests: sleep brake, shared aggregation helper, daily rollup, and /focus-load."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from time import monotonic

import pytest
from httpx import ASGITransport, AsyncClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SATAN_DB_PATH", str(PROJECT_ROOT / "data" / "test_satan.db"))

from satan import db as satan_db
from satan import timer as satan_timer
from satan.activity import get_daily_activity_records, get_daily_totals, rollup_past_days
from satan.db import get_db, initialize_database, local_now
from satan.main import app
from satan.models import TimerState
from satan.timer import finish_phase_after, timer_state


@pytest.fixture(autouse=True)
async def setup_test_db(monkeypatch):
    # DATABASE_PATH is fixed at first import of satan.db, whichever test module that was.
    path = satan_db.DATABASE_PATH
    if path.exists():
        path.unlink()
    await initialize_database()
    for key, value in asdict(TimerState()).items():
        setattr(timer_state, key, value)
    satan_timer.cancel_timer_job()
    # Keep tests silent: no macOS speech synthesis.
    monkeypatch.setattr("satan.timer.announce", lambda _text: None)
    monkeypatch.setattr("satan.routes.pomodoro.announce", lambda _text: None)
    yield
    satan_timer.cancel_timer_job()
    for key, value in asdict(TimerState()).items():
        setattr(timer_state, key, value)
    if path.exists():
        path.unlink()


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def insert_event(db, occurred, event_type="frontmost_application_changed", app_name="Xcode", metadata=None):
    await db.execute(
        """
        INSERT INTO TrackingLogs
            (occurred_at, local_date, source, application_name, url, domain, title, event_type, metadata_json)
        VALUES (?, ?, 'app', ?, NULL, NULL, NULL, ?, ?)
        """,
        (
            occurred.isoformat(timespec="seconds"),
            occurred.date().isoformat(),
            app_name,
            event_type,
            json.dumps(metadata or {}),
        ),
    )
    await db.commit()


def set_running_timer(*, started_ago: int, remaining_total: int) -> None:
    """Put the in-memory timer into a 'running' state as if it started `started_ago` seconds ago."""
    now = local_now()
    timer_state.status = "running"
    timer_state.phase = "work"
    timer_state.remaining_seconds = remaining_total
    timer_state.started_monotonic = monotonic()
    timer_state.started_at = (now - timedelta(seconds=started_ago)).isoformat(timespec="seconds")
    timer_state.ends_at = (now - timedelta(seconds=started_ago) + timedelta(seconds=remaining_total)).isoformat(
        timespec="seconds"
    )
    timer_state.duration_at_start = remaining_total
    timer_state.session_duration = remaining_total


# --- Sleep brake -----------------------------------------------------------------------------


async def test_sleep_event_pauses_timer_at_sleep_time():
    set_running_timer(started_ago=300, remaining_total=900)  # ends 600s from now
    slept_at = local_now() - timedelta(seconds=100)
    async with client() as c:
        res = await c.post(
            "/track",
            json={"source": "app", "event_type": "system_sleep", "occurred_at": slept_at.isoformat()},
        )
        assert res.status_code == 201
        snap = (await c.get("/pomodoro")).json()
    assert snap["status"] == "paused"
    assert snap["pause_reason"] == "system_sleep"
    # ends_at (now+600) minus the sleep moment (now-100) = 700s left, i.e. 200s of work were done.
    assert 695 <= snap["remaining_seconds"] <= 700
    async for db in get_db():
        cursor = await db.execute("SELECT occurred_at FROM TrackingLogs WHERE event_type = 'system_sleep'")
        row = await cursor.fetchone()
        await cursor.close()
    assert row["occurred_at"] == slept_at.isoformat(timespec="seconds")


async def test_sleep_event_pauses_break_phase_too():
    set_running_timer(started_ago=10, remaining_total=300)
    timer_state.phase = "break"
    async with client() as c:
        await c.post("/track", json={"source": "app", "event_type": "system_sleep"})
        snap = (await c.get("/pomodoro")).json()
    assert snap["status"] == "paused"
    assert snap["phase"] == "break"


async def test_stale_sleep_event_before_current_run_is_ignored():
    set_running_timer(started_ago=60, remaining_total=900)
    old_sleep = local_now() - timedelta(hours=2)
    async with client() as c:
        await c.post(
            "/track",
            json={"source": "app", "event_type": "system_sleep", "occurred_at": old_sleep.isoformat()},
        )
        snap = (await c.get("/pomodoro")).json()
    assert snap["status"] == "running"


async def test_future_or_ancient_sleep_timestamp_falls_back_to_now():
    async with client() as c:
        for offset in (timedelta(hours=1), -timedelta(days=3)):
            res = await c.post(
                "/track",
                json={
                    "source": "app",
                    "event_type": "system_sleep",
                    "occurred_at": (local_now() + offset).isoformat(),
                },
            )
            assert res.status_code == 201
    async for db in get_db():
        cursor = await db.execute("SELECT occurred_at FROM TrackingLogs WHERE event_type = 'system_sleep'")
        rows = await cursor.fetchall()
        await cursor.close()
    now = local_now()
    for row in rows:
        assert abs((now - timer_parse(row["occurred_at"])).total_seconds()) < 5


def timer_parse(value):
    from datetime import datetime

    return datetime.fromisoformat(value)


async def test_sleep_event_is_noop_for_idle_and_paused_timer():
    async with client() as c:
        res = await c.post("/track", json={"source": "app", "event_type": "system_sleep"})
        assert res.status_code == 201
        assert (await c.get("/pomodoro")).json()["status"] == "idle"

        await c.post("/pomodoro/start", json={"duration_seconds": 600})
        await c.post("/pomodoro/pause")
        await c.post("/track", json={"source": "app", "event_type": "system_sleep"})
        snap = (await c.get("/pomodoro")).json()
    assert snap["status"] == "paused"
    assert snap["pause_reason"] == "manual"  # the earlier manual pause is not overwritten


async def test_occurred_at_is_ignored_for_regular_events():
    long_ago = local_now() - timedelta(hours=5)
    async with client() as c:
        await c.post(
            "/track",
            json={"source": "app", "application_name": "Xcode", "occurred_at": long_ago.isoformat()},
        )
    async for db in get_db():
        cursor = await db.execute("SELECT occurred_at FROM TrackingLogs")
        row = await cursor.fetchone()
        await cursor.close()
    assert abs((local_now() - timer_parse(row["occurred_at"])).total_seconds()) < 5


async def test_resumed_pomodoro_is_credited_full_session_duration():
    async with client() as c:
        await c.post("/pomodoro/start", json={"duration_seconds": 1500})
        await c.post("/pomodoro/pause")
        snap = (await c.post("/pomodoro/resume")).json()
        assert snap["status"] == "running"
        assert snap["pause_reason"] is None
        assert snap["session_duration"] == 1500

    satan_timer.cancel_timer_job()
    await finish_phase_after(0)

    async for db in get_db():
        cursor = await db.execute(
            "SELECT metadata_json FROM TrackingLogs WHERE event_type = 'pomodoro_completed'"
        )
        row = await cursor.fetchone()
        await cursor.close()
    assert json.loads(row["metadata_json"])["duration_seconds"] == 1500
    assert timer_state.phase == "break"


# --- Aggregation ------------------------------------------------------------------------------


async def test_sleep_marker_stops_time_from_accruing_until_next_event():
    day = (local_now() - timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
    async for db in get_db():
        await insert_event(db, day, app_name="Xcode")  # 10:00
        await insert_event(db, day + timedelta(minutes=5), app_name="Arc")  # 10:05
        await insert_event(db, day + timedelta(minutes=20), event_type="system_sleep", app_name=None)
        await insert_event(db, day + timedelta(hours=4), app_name="Xcode")  # 14:00 (wake)
        await insert_event(db, day + timedelta(hours=4, minutes=10), app_name="Arc")  # 14:10
        records = await get_daily_activity_records(db, day.date(), day.date())
    record = records[day.date().isoformat()]
    # 300 (10:00-10:05) + 900 (10:05-10:20, at the cap) + 0 (asleep) + 600 (14:00-14:10) + 60 (last event of a past day)
    assert record["laptop_seconds"] == 300 + 900 + 600 + 60
    assert record["event_count"] == 4  # the sleep marker itself is not an activity event


async def test_trailing_sleep_marker_today_earns_no_time_while_asleep():
    now = local_now()
    async for db in get_db():
        await insert_event(db, now - timedelta(minutes=30), app_name="Xcode")
        await insert_event(db, now - timedelta(minutes=20), event_type="system_sleep", app_name=None)
        records = await get_daily_activity_records(db, now.date(), now.date())
    laptop = records.get(now.date().isoformat(), {}).get("laptop_seconds", 0)
    # Midnight rollover can move events across dates; only assert when both landed on today.
    if (now - timedelta(minutes=30)).date() == now.date():
        assert laptop == 600  # Xcode until the sleep marker; nothing after it


async def test_activity_summary_endpoint_shape_unchanged():
    day = (local_now() - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    async for db in get_db():
        await insert_event(db, day)
        await insert_event(db, day + timedelta(minutes=10), event_type="pomodoro_completed", metadata={"duration_seconds": 1500})
    async with client() as c:
        data = (await c.get("/activity/summary?days=3")).json()
    assert len(data["days"]) == 3
    entry = next(d for d in data["days"] if d["date"] == day.date().isoformat())
    assert set(entry) == {"date", "event_count", "total_laptop_time_seconds", "total_focus_time_seconds"}
    assert entry["total_focus_time_seconds"] == 1500
    assert entry["total_laptop_time_seconds"] == 60


# --- Rollup and /focus-load -------------------------------------------------------------------


async def test_rollup_persists_days_that_retention_will_purge():
    base = (local_now() - timedelta(days=40)).replace(hour=9, minute=0, second=0, microsecond=0)
    async for db in get_db():
        for offset in range(3):
            day = base + timedelta(days=offset)
            await insert_event(db, day)
            await insert_event(db, day + timedelta(minutes=10))
            await insert_event(db, day + timedelta(minutes=20), event_type="pomodoro_completed", metadata={"duration_seconds": 1200})
        assert await rollup_past_days(db) == 3
        assert await rollup_past_days(db) == 0  # idempotent

    await satan_db.cleanup_old_logs(retention_days=30)

    async for db in get_db():
        cursor = await db.execute("SELECT COUNT(*) AS n FROM TrackingLogs")
        assert (await cursor.fetchone())["n"] == 0  # raw logs purged...
        await cursor.close()
        totals = await get_daily_totals(db, base.date(), base.date() + timedelta(days=2))
    assert len(totals) == 3  # ...but the rollup still has the days
    first = totals[base.date().isoformat()]
    assert first["focus_seconds"] == 1200
    assert first["laptop_seconds"] == 600 + 60  # 9:00->9:10 gap, then 60s for the last event of a past day


async def test_focus_load_endpoint_with_no_data():
    async with client() as c:
        res = await c.get("/focus-load")
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "insufficient_data"
    assert data["daysTracked"] == 0
    assert data["classification"] is None
    assert data["history"] == []
    assert data["rangeDays"] == 30
    assert set(data["today"]) == {"focusMinutes", "laptopMinutes"}


async def test_focus_load_endpoint_operational_with_rolled_up_history():
    today = local_now().date()
    async for db in get_db():
        for offset in range(1, 40):
            day = (today - timedelta(days=offset)).isoformat()
            focus = 3600 if offset > 7 else 7200  # last week doubles the load
            await db.execute(
                "INSERT INTO DailyActivityRollup (local_date, laptop_seconds, focus_seconds, updated_at) VALUES (?, ?, ?, ?)",
                (day, 18000, focus, local_now().isoformat()),
            )
        await db.commit()
    async with client() as c:
        data = (await c.get("/focus-load")).json()
    assert data["state"] == "operational"
    assert data["daysTracked"] == 40
    assert data["classification"] in {"above", "well_above"}
    assert data["acuteLoad"] > data["chronicLoad"]
    assert data["history"][-1]["date"] == today.isoformat()
    assert data["rangeDays"] == 30
    assert len(data["history"]) == 30
    # 40 days of data: the newest day has a full 28-day baseline, the oldest chart day does not.
    assert data["history"][-1]["chronicPartial"] is False
    assert data["history"][0]["chronicPartial"] is True


async def test_focus_load_range_param():
    today = local_now().date()
    async for db in get_db():
        for offset in range(1, 41):
            await db.execute(
                "INSERT INTO DailyActivityRollup (local_date, laptop_seconds, focus_seconds, updated_at) VALUES (?, ?, ?, ?)",
                ((today - timedelta(days=offset)).isoformat(), 18000, 3600, local_now().isoformat()),
            )
        await db.commit()
    async with client() as c:
        d30 = (await c.get("/focus-load?days=30")).json()
        d60 = (await c.get("/focus-load?days=60")).json()
        d90 = (await c.get("/focus-load?days=90")).json()
        assert (await c.get("/focus-load?days=3")).status_code == 422
    assert [len(d["history"]) for d in (d30, d60, d90)] == [30, 41, 41]  # capped at the 41 tracked days
    assert [d["rangeDays"] for d in (d30, d60, d90)] == [30, 60, 90]
    # The headline numbers describe "now", not the chart window.
    assert d30["classification"] == d60["classification"] == d90["classification"]
    assert d30["acuteLoad"] == d90["acuteLoad"]
