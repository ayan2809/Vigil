"""Focus Load: acute (7-day) vs chronic (28-day) focus volume, Apple Training Load style.

Pure functions only — no DB access, no I/O. The route layer supplies zero-padded daily records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACUTE_DAYS = 7
CHRONIC_DAYS = 28
HISTORY_DAYS = 28


def records_needed(history_days: int) -> int:
    """Days of records so every history day has a full 28-day chronic window behind it."""
    return history_days + CHRONIC_DAYS - 1


RECORD_DAYS = records_needed(HISTORY_DAYS)

TREND_MIN_CHANGE_POINTS = 5.0
STEADY_UPPER_BOUND = 10.0


@dataclass(frozen=True)
class DailyRecord:
    date: str
    focus_minutes: float
    laptop_minutes: float


def compute_density(focus_minutes: float, laptop_minutes: float) -> float:
    """Focus / laptop time, clamped to 0..1. Focus with no laptop time counts as fully dense."""
    if laptop_minutes <= 0:
        return 1.0 if focus_minutes > 0 else 0.0
    return max(0.0, min(focus_minutes / laptop_minutes, 1.0))


def compute_daily_flu(focus_minutes: float, laptop_minutes: float) -> float:
    """Focus Load Unit for one day: focus minutes weighted 0.5x..1.0x by density."""
    return focus_minutes * (0.5 + 0.5 * compute_density(focus_minutes, laptop_minutes))


def compute_delta_percent(acute: float, chronic: float) -> float:
    if chronic == 0:
        return 0.0
    return (acute - chronic) / chronic * 100.0


def classify_delta(delta_percent: float) -> str:
    if delta_percent < -20:
        return "well_below"
    if delta_percent < -5:
        return "below"
    if delta_percent <= 10:
        return "steady"
    if delta_percent <= 30:
        return "above"
    return "well_above"


def classify_state(days_tracked: int) -> str:
    if days_tracked < ACUTE_DAYS:
        return "insufficient_data"
    if days_tracked < CHRONIC_DAYS:
        return "preliminary"
    return "operational"


def classify_trend(delta_now: float | None, delta_week_ago: float | None) -> str | None:
    """Is load rising, falling, or stable versus a week ago?"""
    if delta_now is None or delta_week_ago is None:
        return None
    change = delta_now - delta_week_ago
    if change >= TREND_MIN_CHANGE_POINTS and delta_now > STEADY_UPPER_BOUND:
        return "rising"
    if change <= -TREND_MIN_CHANGE_POINTS:
        return "falling"
    return "stable"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_focus_load(
    daily_records: list[DailyRecord], days_tracked: int, history_days: int = HISTORY_DAYS
) -> dict[str, Any]:
    """Build the `/focus-load` payload.

    ``daily_records`` is oldest-first and ends today (today included in the acute window, and
    partial while the day is in progress), zero-padded for missing days. ``days_tracked`` is the
    number of calendar days since the first recorded data; records before that are padding and are
    excluded from every average. Pass ``records_needed(history_days)`` records for a full history
    series. ``history`` covers the last ``history_days`` days but only from the first tracked day on,
    so a short history is not padded with empty days.
    """
    count = len(daily_records)
    days_tracked = max(0, days_tracked)
    first_tracked_index = max(0, count - days_tracked)
    flus = [compute_daily_flu(r.focus_minutes, r.laptop_minutes) for r in daily_records]

    def window_stats(index: int) -> dict[str, Any]:
        """Rolling stats as of ``index``, using only tracked days."""
        available = index - max(first_tracked_index, index - (CHRONIC_DAYS - 1)) + 1
        if index < first_tracked_index or available < ACUTE_DAYS:
            return {"acute": None, "chronic": None, "delta": None, "partial": available < CHRONIC_DAYS}
        acute = _mean(flus[index - ACUTE_DAYS + 1 : index + 1])
        chronic = _mean(flus[index - available + 1 : index + 1])
        return {
            "acute": acute,
            "chronic": chronic,
            "delta": compute_delta_percent(acute, chronic),
            "partial": available < CHRONIC_DAYS,
        }

    history = []
    history_start = max(first_tracked_index, count - history_days)
    for index in range(history_start, count):
        record = daily_records[index]
        stats = window_stats(index)
        delta = stats["delta"]
        history.append(
            {
                "date": record.date,
                "flu": round(flus[index], 1),
                "focusMinutes": round(record.focus_minutes, 1),
                "laptopMinutes": round(record.laptop_minutes, 1),
                "density": round(compute_density(record.focus_minutes, record.laptop_minutes), 3),
                "acuteLoad": None if stats["acute"] is None else round(stats["acute"], 1),
                "chronicLoad": None if stats["chronic"] is None else round(stats["chronic"], 1),
                "chronicPartial": stats["partial"],
                "deltaPercent": None if delta is None else round(delta, 1),
                "classification": None if delta is None else classify_delta(delta),
            }
        )

    state = classify_state(days_tracked)
    today_record = daily_records[-1] if daily_records else DailyRecord("", 0.0, 0.0)
    latest = window_stats(count - 1) if count else window_stats(0)
    week_ago = window_stats(count - 1 - ACUTE_DAYS) if count > ACUTE_DAYS else None

    acute_window = daily_records[max(0, count - ACUTE_DAYS) :]
    acute_focus = _mean([r.focus_minutes for r in acute_window])
    acute_density = compute_density(
        sum(r.focus_minutes for r in acute_window), sum(r.laptop_minutes for r in acute_window)
    )
    chronic_span = min(days_tracked, CHRONIC_DAYS, count)
    chronic_focus = _mean([r.focus_minutes for r in daily_records[count - chronic_span :]])

    computed = state != "insufficient_data" and latest["delta"] is not None
    delta = latest["delta"] if computed else None
    return {
        "state": state,
        "daysTracked": days_tracked,
        "classification": classify_delta(delta) if delta is not None else None,
        "deltaPercent": None if delta is None else round(delta, 1),
        "trend": classify_trend(delta, week_ago["delta"] if week_ago else None) if computed else None,
        "acuteLoad": round(latest["acute"], 1) if computed else None,
        "chronicLoad": round(latest["chronic"], 1) if computed else None,
        "acuteFocusMinutesPerDay": round(acute_focus, 1) if computed else None,
        "chronicFocusMinutesPerDay": round(chronic_focus, 1) if computed else None,
        "densityScore": round(compute_density(today_record.focus_minutes, today_record.laptop_minutes), 3),
        "acuteDensity": round(acute_density, 3),
        "today": {
            "focusMinutes": round(today_record.focus_minutes, 1),
            "laptopMinutes": round(today_record.laptop_minutes, 1),
        },
        "history": history,
    }
