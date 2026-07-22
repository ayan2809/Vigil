"""Integration and unit tests for Vigil backend API and timer state recovery."""

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
TEST_DB_PATH = PROJECT_ROOT / "data" / "test_vigil.db"
os.environ["VIGIL_DB_PATH"] = str(TEST_DB_PATH)

from vigil.db import initialize_database, get_db
from vigil.main import app
from vigil.timer import load_persisted_timer_state, timer_snapshot, timer_state


@pytest.fixture(autouse=True)
async def setup_test_db():
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    await initialize_database()
    yield
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_tasks_crud():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create Task
        res = await client.post("/tasks", json={"title": "Test Task", "estimate_pomodoros": 3})
        assert res.status_code == 201
        data = res.json()
        task_id = data["id"]
        assert data["title"] == "Test Task"
        assert data["estimate_pomodoros"] == 3

        # Get Tasks
        res = await client.get("/tasks")
        assert res.status_code == 200
        tasks = res.json()
        assert len(tasks) == 1

        # Patch Task
        res = await client.patch(f"/tasks/{task_id}", json={"title": "Updated Task", "completed_pomodoros": 1})
        assert res.status_code == 200
        assert res.json()["title"] == "Updated Task"

        # Delete Task
        res = await client.delete(f"/tasks/{task_id}")
        assert res.status_code == 204

        # Verify Deleted
        res = await client.get(f"/tasks/{task_id}")
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_tracking_and_summary():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Post Webhook
        res = await client.post("/track", json={
            "source": "browser",
            "application_name": "Google Chrome",
            "url": "https://github.com/test",
            "title": "GitHub",
            "event_type": "tab_activated",
            "metadata": {"tab_id": 1}
        })
        assert res.status_code == 201
        assert "id" in res.json()

        # Check Active Time Summary
        res = await client.get("/active-time-summary")
        assert res.status_code == 200
        summary_data = res.json()
        assert "totalSeconds" in summary_data
        assert "apps" in summary_data

        # Check Activity Summary
        res = await client.get("/activity/summary?days=7")
        assert res.status_code == 200
        act_data = res.json()
        assert len(act_data["days"]) == 7


@pytest.mark.asyncio
async def test_pomodoro_lifecycle_and_persistence():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Start Pomodoro
        res = await client.post("/pomodoro/start", json={"duration_seconds": 60})
        assert res.status_code == 200
        snap = res.json()
        assert snap["status"] == "running"
        assert snap["remaining_seconds"] == 60

        # Pause Pomodoro
        res = await client.post("/pomodoro/pause")
        assert res.status_code == 200
        snap = res.json()
        assert snap["status"] == "paused"

        # Simulate Server Restart by clearing in-memory state and re-loading from SQLite
        timer_state.status = "idle"
        timer_state.remaining_seconds = 0

        # Load persisted state
        await load_persisted_timer_state()
        restored_snap = await timer_snapshot()
        assert restored_snap["status"] == "paused"

        # Resume Pomodoro
        res = await client.post("/pomodoro/resume")
        assert res.status_code == 200
        assert res.json()["status"] == "running"

        # Stop Pomodoro
        res = await client.post("/pomodoro/stop")
        assert res.status_code == 200
        assert res.json()["status"] == "idle"
