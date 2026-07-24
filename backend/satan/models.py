"""Pydantic schemas and dataclasses for Satan backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

DEFAULT_WORK_SECONDS = int(os.environ.get("SATAN_WORK_SECONDS", os.environ.get("VIGIL_WORK_SECONDS", "1500")))
DEFAULT_BREAK_SECONDS = int(os.environ.get("SATAN_BREAK_SECONDS", os.environ.get("VIGIL_BREAK_SECONDS", "300")))


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    estimate_pomodoros: int = Field(default=1, ge=1, le=99)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["todo", "in_progress", "done"] | None = None
    estimate_pomodoros: int | None = Field(default=None, ge=1, le=99)
    completed_pomodoros: int | None = Field(default=None, ge=0, le=9999)


class TrackingEvent(BaseModel):
    source: Literal["browser", "app"]
    application_name: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=4096)
    title: str | None = Field(default=None, max_length=1000)
    event_type: str = Field(default="active_change", min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PomodoroStart(BaseModel):
    task_id: int | None = Field(default=None, ge=1)
    duration_seconds: int = Field(default=DEFAULT_WORK_SECONDS, ge=1, le=14_400)


@dataclass
class TimerState:
    status: Literal["idle", "running", "paused"] = "idle"
    phase: Literal["work", "break"] = "work"
    task_id: int | None = None
    remaining_seconds: int = 0
    started_monotonic: float | None = None
    ends_at: str | None = None
    sessions_completed: int = 0
    started_at: str | None = None
    duration_at_start: int = 0


class UserSettings(BaseModel):
    pomodoro_duration_minutes: int = Field(default=25, ge=1, le=120)
    sleep_time: str = Field(default="23:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    reflection_email: str | None = Field(default=None, max_length=320)


class SettingsUpdate(BaseModel):
    pomodoro_duration_minutes: int | None = Field(default=None, ge=1, le=120)
    sleep_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    reflection_email: str | None = Field(default=None, max_length=320)

