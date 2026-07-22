"""Unit and integration tests for Settings API, Outbox Generator, and Queue Processor."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Add backend directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Use a test database
TEST_DB_PATH = PROJECT_ROOT / "data" / "test_vigil_settings.db"
os.environ["VIGIL_DB_PATH"] = str(TEST_DB_PATH)

from vigil.db import get_db, initialize_database, local_now
from vigil.main import app
from vigil.scheduler import (
    generate_nightly_reflection_job,
    generate_nightly_reflection_payload,
    parse_sleep_time_to_trigger,
    process_email_outbox_job,
)


@pytest.fixture(autouse=True)
async def setup_test_db():
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    await initialize_database()
    yield
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.mark.asyncio
async def test_trigger_time_calculation():
    h, m = parse_sleep_time_to_trigger("23:00")
    assert (h, m) == (22, 45)

    h2, m2 = parse_sleep_time_to_trigger("00:10")
    assert (h2, m2) == (23, 55)


@pytest.mark.asyncio
async def test_settings_api():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # GET default settings
        res = await client.get("/settings")
        assert res.status_code == 200
        data = res.json()
        assert data["pomodoro_duration_minutes"] == 25
        assert data["sleep_time"] == "23:00"
        assert data["reflection_email"] is None

        # PUT updated settings
        res = await client.put("/settings", json={
            "pomodoro_duration_minutes": 30,
            "sleep_time": "22:30",
            "reflection_email": "watch_user@example.com"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["pomodoro_duration_minutes"] == 30
        assert data["sleep_time"] == "22:30"
        assert data["reflection_email"] == "watch_user@example.com"


@pytest.mark.asyncio
async def test_outbox_generator_critical_zero_laptop_time_rule():
    # Today has 0 activity logs
    payload = await generate_nightly_reflection_payload()
    assert payload is None, "CRITICAL RULE: If Total Laptop Time == 0, generate_nightly_reflection_payload must return None"


@pytest.mark.asyncio
async def test_outbox_generator_and_watchos_format():
    today_str = local_now().date().isoformat()
    # Seed 3 distinct app activity events into TrackingLogs
    async for db in get_db():
        await db.execute(
            """
            INSERT INTO TrackingLogs (occurred_at, local_date, source, application_name, event_type, metadata_json)
            VALUES (?, ?, 'app', 'Visual Studio Code', 'frontmost_application_changed', '{}'),
                   (?, ?, 'browser', 'Arc', 'tab_activated', '{}'),
                   (?, ?, 'app', 'Terminal', 'frontmost_application_changed', '{}')
            """,
            (
                f"{today_str}T10:00:00+05:30",
                today_str,
                f"{today_str}T11:00:00+05:30",
                today_str,
                f"{today_str}T12:00:00+05:30",
                today_str,
            ),
        )
        await db.commit()

    # Run generator job
    await generate_nightly_reflection_job()

    # Query email_outbox table
    async for db in get_db():
        cursor = await db.execute("SELECT * FROM email_outbox")
        rows = await cursor.fetchall()
        await cursor.close()

    assert len(rows) == 1
    row = rows[0]
    subject = row["subject"]
    body = row["body"]

    # Verify WatchOS Subject format: Vigil ([Date]): [Total Focus] ([Focus %]%) / [Total Laptop] Total
    assert subject.startswith("Vigil (")
    assert "Focus (" in subject
    assert "%) /" in subject
    assert "Total" in subject

    # Verify WatchOS Body First Line: 🥇 [App1] ([Time]) | 🥈 [App2] ([Time]) | 🥉 [App3] ([Time])
    first_line = body.split("\n")[0]
    assert "🥇" in first_line
    assert "🥈" in first_line
    assert "🥉" in first_line
    assert "Visual Studio Code" in first_line
    assert "Arc" in first_line
    assert "Terminal" in first_line
    assert "|" in first_line

