"""User settings API router."""

from __future__ import annotations

from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends
from vigil.db import get_db, iso_now
from vigil.models import SettingsUpdate, UserSettings

router = APIRouter(prefix="/settings", tags=["settings"])


async def get_user_settings(db: aiosqlite.Connection) -> dict[str, Any]:
    cursor = await db.execute("SELECT * FROM user_settings WHERE id = 1")
    row = await cursor.fetchone()
    await cursor.close()
    if not row:
        now = iso_now()
        await db.execute(
            """
            INSERT INTO user_settings (id, pomodoro_duration_minutes, sleep_time, reflection_email, updated_at)
            VALUES (1, 25, '23:00', NULL, ?)
            """,
            (now,),
        )
        await db.commit()
        return {
            "pomodoro_duration_minutes": 25,
            "sleep_time": "23:00",
            "reflection_email": None,
        }
    return {
        "pomodoro_duration_minutes": row["pomodoro_duration_minutes"],
        "sleep_time": row["sleep_time"],
        "reflection_email": row["reflection_email"],
    }


@router.get("", response_model=UserSettings)
async def read_settings(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    return await get_user_settings(db)


@router.put("", response_model=UserSettings)
async def update_settings(
    payload: SettingsUpdate, db: aiosqlite.Connection = Depends(get_db)
) -> dict[str, Any]:
    current = await get_user_settings(db)
    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        return current

    new_duration = changes.get("pomodoro_duration_minutes", current["pomodoro_duration_minutes"])
    new_sleep_time = changes.get("sleep_time", current["sleep_time"])
    new_email = changes.get("reflection_email", current["reflection_email"])
    if new_email is not None and not new_email.strip():
        new_email = None

    now = iso_now()
    await db.execute(
        """
        UPDATE user_settings
        SET pomodoro_duration_minutes = ?,
            sleep_time = ?,
            reflection_email = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (new_duration, new_sleep_time, new_email, now),
    )
    await db.commit()

    # If scheduler is active, update the nightly outbox generator trigger time
    try:
        from vigil.scheduler import update_nightly_job_trigger
        update_nightly_job_trigger(new_sleep_time)
    except Exception:
        pass

    return {
        "pomodoro_duration_minutes": new_duration,
        "sleep_time": new_sleep_time,
        "reflection_email": new_email,
    }
