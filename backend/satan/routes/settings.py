import json
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends
from satan.db import DEFAULT_CORE_VALUES, DEFAULT_MONTHLY_GOAL, get_db, iso_now
from satan.models import SettingsUpdate, UserSettings

router = APIRouter(prefix="/settings", tags=["settings"])


async def get_user_settings(db: aiosqlite.Connection) -> dict[str, Any]:
    cursor = await db.execute("SELECT * FROM user_settings WHERE id = 1")
    row = await cursor.fetchone()
    await cursor.close()
    if not row:
        now = iso_now()
        default_values_json = json.dumps(DEFAULT_CORE_VALUES)
        await db.execute(
            """
            INSERT INTO user_settings (id, pomodoro_duration_minutes, sleep_time, reflection_email, monthly_goal, core_values, updated_at)
            VALUES (1, 25, '23:00', NULL, ?, ?, ?)
            """,
            (DEFAULT_MONTHLY_GOAL, default_values_json, now),
        )
        await db.commit()
        return {
            "pomodoro_duration_minutes": 25,
            "sleep_time": "23:00",
            "reflection_email": None,
            "monthly_goal": DEFAULT_MONTHLY_GOAL,
            "core_values": DEFAULT_CORE_VALUES,
        }

    keys = row.keys()
    monthly_goal_val = row["monthly_goal"] if ("monthly_goal" in keys and row["monthly_goal"] is not None) else DEFAULT_MONTHLY_GOAL

    core_values_raw = row["core_values"] if ("core_values" in keys and row["core_values"]) else None
    if core_values_raw:
        try:
            core_values_list = json.loads(core_values_raw)
        except Exception:
            core_values_list = DEFAULT_CORE_VALUES
    else:
        core_values_list = DEFAULT_CORE_VALUES

    return {
        "pomodoro_duration_minutes": row["pomodoro_duration_minutes"],
        "sleep_time": row["sleep_time"],
        "reflection_email": row["reflection_email"],
        "monthly_goal": monthly_goal_val,
        "core_values": core_values_list,
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

    new_goal = changes.get("monthly_goal", current["monthly_goal"])
    new_values = changes.get("core_values", current["core_values"])
    if isinstance(new_values, list):
        new_values_json = json.dumps(new_values)
    else:
        new_values_json = json.dumps(current.get("core_values") or DEFAULT_CORE_VALUES)

    now = iso_now()
    await db.execute(
        """
        UPDATE user_settings
        SET pomodoro_duration_minutes = ?,
            sleep_time = ?,
            reflection_email = ?,
            monthly_goal = ?,
            core_values = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (new_duration, new_sleep_time, new_email, new_goal, new_values_json, now),
    )
    await db.commit()

    # If scheduler is active, update the nightly outbox generator trigger time
    try:
        from satan.scheduler import update_nightly_job_trigger
        update_nightly_job_trigger(new_sleep_time)
    except Exception:
        pass

    return {
        "pomodoro_duration_minutes": new_duration,
        "sleep_time": new_sleep_time,
        "reflection_email": new_email,
        "monthly_goal": new_goal,
        "core_values": new_values if isinstance(new_values, list) else current.get("core_values", DEFAULT_CORE_VALUES),
    }
