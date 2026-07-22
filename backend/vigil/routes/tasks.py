"""Task management API router."""

from __future__ import annotations

from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response, status
from vigil.db import get_db, iso_now
from vigil.models import TaskCreate, TaskUpdate
from vigil.timer import timer_lock, timer_state

router = APIRouter(prefix="/tasks", tags=["tasks"])


def task_from_row(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)


async def get_task_or_404(db: aiosqlite.Connection, task_id: int) -> dict[str, Any]:
    cursor = await db.execute("SELECT * FROM PomodoroTasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task_from_row(row)


@router.get("", response_model=list[dict[str, Any]])
async def list_tasks(db: aiosqlite.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    cursor = await db.execute(
        """
        SELECT * FROM PomodoroTasks
        ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END,
                 updated_at DESC
        """
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [task_from_row(row) for row in rows]


@router.get("/{task_id}", response_model=dict[str, Any])
async def get_task(task_id: int, db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    return await get_task_or_404(db, task_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=dict[str, Any])
async def create_task(payload: TaskCreate, db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title cannot be blank")
    now = iso_now()
    cursor = await db.execute(
        """
        INSERT INTO PomodoroTasks (title, estimate_pomodoros, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (title, payload.estimate_pomodoros, now, now),
    )
    await db.commit()
    task_id = cursor.lastrowid
    await cursor.close()
    return await get_task_or_404(db, task_id)


@router.patch("/{task_id}", response_model=dict[str, Any])
async def update_task(
    task_id: int, payload: TaskUpdate, db: aiosqlite.Connection = Depends(get_db)
) -> dict[str, Any]:
    await get_task_or_404(db, task_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return await get_task_or_404(db, task_id)
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title cannot be blank")
    changes["updated_at"] = iso_now()
    assignments = ", ".join(f"{column} = ?" for column in changes)
    values = [*changes.values(), task_id]
    await db.execute(f"UPDATE PomodoroTasks SET {assignments} WHERE id = ?", values)
    await db.commit()
    return await get_task_or_404(db, task_id)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, db: aiosqlite.Connection = Depends(get_db)) -> Response:
    await get_task_or_404(db, task_id)
    async with timer_lock:
        if timer_state.task_id == task_id and timer_state.status != "idle":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stop the active Pomodoro before deleting its task",
            )
    await db.execute("DELETE FROM PomodoroTasks WHERE id = ?", (task_id,))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
