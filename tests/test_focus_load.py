"""Unit tests for the pure Focus Load calculation module."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from satan.focus_load import (
    RECORD_DAYS,
    DailyRecord,
    classify_delta,
    classify_state,
    classify_trend,
    compute_daily_flu,
    compute_delta_percent,
    compute_density,
    compute_focus_load,
)


def make_records(focus_minutes: list[float], laptop_minutes: float = 100.0) -> list[DailyRecord]:
    """Oldest-first records ending today; shorter lists are left-padded with zeros."""
    padded = [0.0] * (RECORD_DAYS - len(focus_minutes)) + list(focus_minutes)
    end = date(2026, 9, 29)
    start = end - timedelta(days=RECORD_DAYS - 1)
    return [
        DailyRecord((start + timedelta(days=i)).isoformat(), focus, laptop_minutes if focus else 0.0)
        for i, focus in enumerate(padded)
    ]


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (-100, "well_below"),
        (-20.01, "well_below"),
        (-20, "below"),
        (-19.99, "below"),
        (-5.01, "below"),
        (-5, "steady"),
        (-4.99, "steady"),
        (0, "steady"),
        (10, "steady"),
        (10.01, "above"),
        (30, "above"),
        (30.01, "well_above"),
        (400, "well_above"),
    ],
)
def test_classification_boundaries(delta, expected):
    assert classify_delta(delta) == expected


def test_zero_chronic_load_gives_zero_delta():
    assert compute_delta_percent(50.0, 0.0) == 0.0
    assert compute_delta_percent(0.0, 0.0) == 0.0


def test_density_edge_cases():
    assert compute_density(30, 0) == 1.0  # focus without laptop time: no crash, fully dense
    assert compute_density(0, 0) == 0.0
    assert compute_density(120, 60) == 1.0  # focus > laptop clamps
    assert compute_density(30, 60) == 0.5


def test_daily_flu_weights_by_density():
    assert compute_daily_flu(60, 60) == 60  # fully dense: 1.0x
    assert compute_daily_flu(30, 60) == pytest.approx(22.5)  # density 0.5: 0.75x
    assert compute_daily_flu(60, 0) == 60  # no laptop time: density 1.0
    assert compute_daily_flu(120, 60) == 120  # clamped density, not >1.0
    assert compute_daily_flu(0, 60) == 0


@pytest.mark.parametrize(
    ("days", "state"),
    [(0, "insufficient_data"), (6, "insufficient_data"), (7, "preliminary"), (27, "preliminary"), (28, "operational"), (39, "operational")],
)
def test_cold_start_states(days, state):
    assert classify_state(days) == state
    result = compute_focus_load(make_records([60.0] * min(days, RECORD_DAYS)), days)
    assert result["state"] == state
    if state == "insufficient_data":
        assert result["classification"] is None
        assert result["deltaPercent"] is None
        assert result["acuteLoad"] is None
    else:
        assert result["classification"] is not None


def test_today_counts_toward_acute_load():
    quiet = [60.0] * 40
    baseline = compute_focus_load(make_records(quiet + [0.0]), 41)
    with_today = compute_focus_load(make_records(quiet + [240.0]), 41)
    assert with_today["acuteLoad"] > baseline["acuteLoad"]
    assert with_today["today"]["focusMinutes"] == 240.0


def test_steady_workload_is_steady():
    result = compute_focus_load(make_records([60.0] * 40), 40)
    assert result["deltaPercent"] == 0.0
    assert result["classification"] == "steady"
    assert result["trend"] == "stable"


def test_overload_is_detected_and_trend_rises():
    # 4 weeks of 60 min/day, then a week at 120 min/day.
    result = compute_focus_load(make_records([60.0] * 33 + [120.0] * 7), 40)
    assert result["classification"] in {"above", "well_above"}
    assert result["deltaPercent"] > 10
    assert result["acuteLoad"] > result["chronicLoad"]
    assert result["trend"] == "rising"


def test_underload_trend_falls():
    result = compute_focus_load(make_records([120.0] * 33 + [30.0] * 7), 40)
    assert result["classification"] in {"below", "well_below"}
    assert result["trend"] == "falling"


def test_history_shape_and_rolling_nulls():
    result = compute_focus_load(make_records([60.0] * 10), 10)
    history = result["history"]
    assert len(history) == 10  # only tracked days, not padded out to the 28-day window
    assert history[-1]["date"] == "2026-09-29"
    tracked = [h for h in history if h["acuteLoad"] is not None]
    assert len(tracked) == 4  # 10 tracked days: only days 7..10 have a full acute window
    assert all(h["chronicPartial"] for h in history)
    assert history[0]["acuteLoad"] is None
    assert history[0]["classification"] is None


def test_history_window_follows_history_days():
    records = make_records([60.0] * 40)
    assert len(compute_focus_load(records, 40)["history"]) == 28
    assert len(compute_focus_load(records, 40, history_days=30)["history"]) == 30
    assert len(compute_focus_load(records, 40, history_days=10)["history"]) == 10
    # Asking for more days than exist only returns the tracked days.
    assert len(compute_focus_load(records, 40, history_days=90)["history"]) == 40


def test_chronic_partial_flips_at_28_tracked_days():
    result = compute_focus_load(make_records([60.0] * 40), 40)
    history = result["history"]
    assert history[-1]["chronicPartial"] is False
    result_27 = compute_focus_load(make_records([60.0] * 27), 27)
    assert result_27["history"][-1]["chronicPartial"] is True
    result_28 = compute_focus_load(make_records([60.0] * 28), 28)
    assert result_28["history"][-1]["chronicPartial"] is False


def test_untracked_padding_does_not_drag_down_chronic_load():
    # 10 tracked days of 60 min, with 45 padded zero days before them.
    result = compute_focus_load(make_records([60.0] * 10), 10)
    assert result["chronicLoad"] == pytest.approx(result["acuteLoad"])
    assert result["deltaPercent"] == 0.0


def test_trend_thresholds():
    assert classify_trend(None, 5) is None
    assert classify_trend(5, None) is None
    assert classify_trend(25, 15) == "rising"
    assert classify_trend(8, 0) == "stable"  # grew, but still inside the steady band
    assert classify_trend(12, 10) == "stable"  # rising less than 5 points
    assert classify_trend(0, 10) == "falling"


def test_empty_records_do_not_crash():
    result = compute_focus_load([], 0)
    assert result["state"] == "insufficient_data"
    assert result["history"] == []
