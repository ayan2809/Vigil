# Plan: "Focus Load" (Acute vs. Chronic Workload Tracker)

> Status: **implemented on branch `feature/progressive-overload`.** This document was written
> before any code changed; all five open questions were resolved in review round 1 (see
> [Decisions](#decisions-from-review-round-1)). Two things surfaced while investigating those answers
> and are called out in [Findings that changed scope](#findings-that-changed-scope).

## 1. Objective

Add an Apple Fitness "Training Load"-style metric: compare the user's short-term focus volume
(**Acute Load**, last 7 days, *including today*) against their conditioned baseline (**Chronic
Load**, last 28 days), express it as a variance %, and classify it into one of five states (Well
Below / Below / Steady / Above / Well Above). Surface it on the dashboard as an Apple-Health-style
interactive trend chart, next to the existing tile/heatmap stats (which stay as they are).

Two supporting pieces are required for the numbers to be trustworthy:

- **Sleep/lid/display brake** — stop counting focus and laptop time, and auto-pause the Pomodoro,
  when the lid closes or the display goes to power saving (Section 6).
- **Daily rollup table** — so history survives the 30-day log purge (Section 4).

## Decisions from review round 1

| # | Question | Decision |
|---|---|---|
| 1 | Does today count toward Acute Load? | **Yes**, live, like Apple. UI says "as of now" and the number moves through the day. |
| 2 | How is "days tracked" defined for cold start? | Measured from the first day with data. The DB already spans **2026-08-22 → today (39 days)**, so this install is `operational` immediately; `insufficient_data` / `preliminary` still exist for fresh installs. Source of truth is the rollup table (Section 4), not raw logs, because raw logs are purged. |
| 3 | Focus can exceed laptop time | Root cause is the Pomodoro timer running while the machine is asleep (focus is credited in full, laptop time isn't). **Fix at the source** with the sleep brake (Section 6). Keep the `min(ratio, 1.0)` clamp as a defensive backstop only. |
| 4 | Density / graph | **Density tile shows today's density** (7-day avg also returned). New **Apple-Health-style chart** (Section 5): daily load, 7-day and 28-day average lines, hover shows that day's load %, and a readout of whether load is progressively rising. Existing tile/heatmap unchanged. |
| 5 | Extract the shared aggregation SQL? | **Yes — decided.** It is no longer optional: the sleep brake (Section 6) must change the duration logic, and that logic is duplicated in 3 places (`summary.py` ×2, `scheduler.py`). Extracting first means one fix instead of three, and `/focus-load` doesn't add a 4th copy. |

## Findings that changed scope

1. **Log retention will eat your history.** `cleanup_old_logs(30)` runs on every backend startup
   (`backend/satan/main.py:22`) and deletes `TrackingLogs` older than 30 days. The DB currently holds
   39 days only because the server hasn't restarted recently — the next restart deletes ~9 of them.
   30 days covers the 28-day chronic window, but not a *rolling* 28-day average across a 28-day chart
   (needs ~56 days). So daily totals need to be persisted separately (Section 4).
2. **Resuming a Pomodoro under-credits focus (existing bug).** `resume` sets
   `duration_at_start = remaining_seconds` (`routes/pomodoro.py:104`), and completion credits
   `duration_at_start` as the focus duration (`timer.py:170`). Pause a 25-min session at minute 10,
   resume, finish → only 15 min is logged. Auto-pause on lid close would make this common, so it is
   fixed as part of this work (Section 6.4).

## 2. Where the logic lives: backend, not frontend

The original spec assumed `focusLoadCalculator.ts` and a client-side store. This repo has no
TypeScript, no Redux/Zustand, and no client persistence — the dashboard is a single-file React app
(`dashboard/src/App.jsx`) polling REST endpoints backed by SQLite. So:

- **All computation is Python on the backend** (pure functions, `pytest`-tested).
- The frontend receives a computed JSON payload and only formats/renders it (including the chart
  geometry, which is presentation, not math).

## 3. New API endpoint

`GET /focus-load` — `backend/satan/routes/focus_load.py`, registered in `backend/satan/main.py`,
following the `routes/summary.py` pattern (`Depends(get_db)`).

```jsonc
{
  "state": "insufficient_data" | "preliminary" | "operational",
  "daysTracked": 39,
  "classification": "above" | "below" | "well_below" | "steady" | "well_above" | null,
  "deltaPercent": 18.4,               // (L7 - L28) / L28 * 100; null when insufficient_data
  "trend": "rising" | "falling" | "stable" | null,   // see Section 5
  "acuteLoad": 217.5,                 // L7, FLU/day, includes today
  "chronicLoad": 183.2,               // L28 (L_K during preliminary), FLU/day
  "acuteFocusMinutesPerDay": 225.0,
  "chronicFocusMinutesPerDay": 190.0,
  "densityScore": 0.72,               // TODAY's density (focus / laptop, clamped 0..1)
  "acuteDensity": 0.68,               // 7-day average density, for reference
  "today": { "focusMinutes": 40.0, "laptopMinutes": 95.0 },
  "history": [                        // last 28 days, oldest first, ends today — drives the chart
    {
      "date": "2026-09-29",
      "flu": 34.2,                    // that day's Focus Load Unit
      "focusMinutes": 40.0,
      "laptopMinutes": 95.0,
      "density": 0.42,
      "acuteLoad": 217.5,             // rolling 7-day avg as of that day; null if < 7 days of data
      "chronicLoad": 183.2,           // rolling 28-day avg as of that day; null if < 7 days of data
      "chronicPartial": false,        // true when fewer than 28 days of data backed chronicLoad
      "deltaPercent": 18.4,           // null when acute/chronic null
      "classification": "above"
    }
  ]
}
```

New keys only; no existing response shapes change (CLAUDE.md constraint 5).

## 4. Data layer and pure calculation

### 4.1 Shared aggregation helper (Decision 5)

New helper (e.g. `backend/satan/activity.py`): `get_daily_activity_records(db, start, end)` returning
`[{date, laptop_seconds, focus_seconds, event_count}]`. It owns the single copy of the
`LEAD() OVER (...)` duration SQL (900s cap, ignore-list, and the new sleep-marker rule from
Section 6.3). `routes/summary.py` (both endpoints), `scheduler.py`, and `/focus-load` all call it.
Existing `/activity/summary` response shape and behavior are preserved; its tests must stay green.

### 4.2 `DailyActivityRollup` table (Finding 1)

Additive DDL in `backend/satan/db.py` (`CREATE TABLE IF NOT EXISTS`, no migration framework needed):

```sql
DailyActivityRollup (
  local_date TEXT PRIMARY KEY,
  laptop_seconds INTEGER NOT NULL,
  focus_seconds  INTEGER NOT NULL,
  updated_at TEXT NOT NULL
)
```

- **Finalized days only** (`local_date < today`). Today is always computed live from `TrackingLogs`.
- **Startup order matters:** roll up every past day present in `TrackingLogs` and missing from the
  rollup *before* `cleanup_old_logs` runs. That one-time backfill captures the existing 39 days
  before the purge can touch them.
- Also fill-on-read: if `/focus-load` finds a past date with raw logs but no rollup row, it computes
  and inserts it (covers a backend that stayed up across midnight).
- `days_tracked = (today − MIN(local_date) in rollup ∪ today's logs) + 1`. Not capped at 28 in the
  data; capped only where the algorithm needs it.
- Caveat: the 39 backfilled days were recorded *before* the sleep brake exists, so their laptop time
  can include up to 15 min of over-count per sleep (the existing 900s gap cap). Focus minutes come
  from Pomodoro completions and are unaffected; only historical *density* is slightly low. Not
  correctable from `TrackingLogs` alone (an optional `pmset -g log` backfill is possible later —
  out of scope here).

### 4.3 Calculation module

`backend/satan/focus_load.py` — pure functions, no DB/I/O:

```python
def compute_daily_flu(focus_minutes: float, laptop_minutes: float) -> float:
    density = 1.0 if laptop_minutes <= 0 else min(focus_minutes / laptop_minutes, 1.0)
    return focus_minutes * (0.5 + 0.5 * density)

def compute_focus_load(daily_records, days_tracked) -> FocusLoadResult:
    """Includes today in L7. Also produces the per-day rolling `history` series and `trend`."""
```

Classification thresholds (unchanged):

| Classification | Range |
|---|---|
| `well_below` | `Δ% < -20` |
| `below` | `-20 ≤ Δ% < -5` |
| `steady` | `-5 ≤ Δ% ≤ 10` |
| `above` | `10 < Δ% ≤ 30` |
| `well_above` | `Δ% > 30` |

Cold start: `< 7` days tracked → `insufficient_data`; `7–27` → `preliminary` (chronic computed over the
days available); `≥ 28` → `operational`.

Unit tests (`tests/test_focus_load.py`, plain `pytest`):
- Boundaries at `-20, -19.99, -5, -4.99, 10, 10.01, 30, 30.01`.
- `L28 == 0` → `Δ% == 0`, no division by zero.
- `laptop_minutes == 0` → density `1.0`; `focus > laptop` → density clamped to `1.0`.
- Cold-start boundaries: 6, 7, 27, 28 days tracked.
- Today is included in L7 (a large "today" moves acute load).
- Rolling `history`: first 6 days have `acuteLoad == null`; `chronicPartial` flips at 28 days.
- `trend` cases (Section 5).

## 5. Frontend

Follows repo convention: inline components in `dashboard/src/App.jsx` (like `MonthlyGoalBanner`),
styles appended to `dashboard/src/styles.css`, plain `fetch` + `useState`/`useEffect`. **No new
dependency** — the dashboard has no chart library, so the chart is hand-rolled inline SVG.

1. **Focus Load Summary Card** — classification badge, "Baseline Tunnel" gauge (−40%…+40% track,
   shaded −5%…+10% band, pin at `deltaPercent`), metrics grid, and coaching copy chosen client-side
   from `classification`. The grid's density figure is **today's** (`densityScore`). Copy uses
   "as of now" wording because today is live.
2. **Focus Load Chart (new, Apple-Health style)** — 28 days, driven entirely by `history`:
   - Faint daily-load bars/dots (`flu`).
   - **7-day average line** (acute) and **28-day average line** (chronic). Where acute sits above
     chronic, you are overloading; the gap over time is the answer to "am I progressively
     overloading?".
   - Shaded **maintenance band** around the chronic line (chronic × 0.95…1.10), which is exactly the
     `steady` range, so leaving the band = changing classification.
   - Chronic segments backed by < 28 days of data render dashed (`chronicPartial`).
   - **Hover / touch-scrub:** vertical rule + tooltip for the hovered day showing date, that day's
     load, focus/laptop minutes, density, **load % (Δ%)**, and classification. With no hover it
     shows today's values by default.
   - **Trend readout** above the chart, from server `trend`: compares Δ% now vs. 7 days ago —
     `rising` if it grew by ≥ 5 points and current Δ% > steady band top, `falling` if it dropped by
     ≥ 5 points, else `stable`. Copy e.g. "Load rising — 3rd week above baseline." (Exact copy and
     thresholds are tunable during review of the built UI.)
3. **Existing tile/heatmap: untouched.** The Daily Progress indicator (today's focus vs. baseline)
   stays as a small element inside the summary card, sourced from `today`.

Cold-start states render the "Tracking initial baseline (Day X of 7…)" / "Preliminary baseline
(calibrating…)" copy instead of gauge/lines. Acceptance for the frontend: `npm --prefix dashboard run
build` succeeds and a manual check in the dev server (hover behavior, dark/light, empty data).

## 6. Sleep / lid / display brake

**Problem today:** neither the tracker nor the timer knows about sleep. (a) The Pomodoro completes on
its full duration and logs full focus credit even if the machine slept through part of it. (b)
`mac_tracker.py` only reports frontmost-app changes, so a lid close produces no event; the gap from
the last event to the next one is counted as laptop time up to the 900s cap.

### 6.1 Tracker (`trackers/mac_tracker.py`) — event-driven, no polling

Register additional observers on `NSWorkspace.sharedWorkspace().notificationCenter()` alongside the
existing ones:
`NSWorkspaceWillSleepNotification`, `NSWorkspaceDidWakeNotification`,
`NSWorkspaceScreensDidSleepNotification`, `NSWorkspaceScreensDidWakeNotification`.

- Track two flags (`system_asleep`, `screens_asleep`). "Away" = either is true. Emit **only on
  transitions of "away"**, so a lid close (which fires both) produces one event, not two.
- On entering away: POST `event_type: "system_sleep"` with `metadata.reason`
  (`"system"` or `"display"`) and a **client-side `occurred_at`** (see 6.2 for why).
- On leaving away: **reset `last_process_id = None` and re-emit the current frontmost app.** Without
  this, the existing dedup (`emit_application`'s `last_process_id` check) swallows the first event
  after wake, and time from wake until the next app switch would go untracked.
- HTTP goes through the existing `ThreadPoolExecutor` (constraint 2). Zero `print()` (constraint 4).

### 6.2 Backend ingest (`routes/tracking.py`, `models.py`)

- `TrackingEvent` gains optional `occurred_at` (ISO datetime). The server honors it **only** for
  `system_sleep` events and only if it is not in the future and within a sane window (e.g. ≤ 24 h
  old); otherwise it falls back to `local_now()`. Reason: on a real lid close the machine can freeze
  before the HTTP request completes, so the request may land *after wake* and would otherwise be
  stamped with the wake time — which would defeat the whole point.
- When a `system_sleep` event arrives, after inserting the row, call the auto-pause helper (6.4)
  with the event's timestamp. `system_sleep` is also validated as an allowed `event_type` value
  (currently free-form; no schema change needed).

### 6.3 Aggregation rule (inside the shared helper from 4.1)

`system_sleep` rows **stay in the `LEAD()` window** — so the last real event before sleep gets a
correct duration ending at the sleep time — but are **excluded after duration is computed**, and the
gap *from* a `system_sleep` event forward is forced to `0`. Net effect: time between lid-close and
wake is never counted, including when the last event of today is a sleep marker (avoids the
`strftime('now') - occurred_at` fallback crediting "now" time while asleep). Same rule applies to the
nightly-email query because it uses the same helper.

### 6.4 Timer pause (`timer.py`, `routes/pomodoro.py`, `models.py`)

- Extract the pause logic from `pause_pomodoro` into `pause_timer(db, *, at=None, reason="manual")`
  in `timer.py`, called under `timer_lock` and followed by `save_timer_state` (constraint 6). The
  manual `/pomodoro/pause` route calls it with `reason="manual"`; the sleep path calls it with
  `reason="system_sleep"`.
- For an auto-pause, remaining time is computed from the **wall-clock `ends_at` minus the sleep
  timestamp**, not from `monotonic()`. This is robust to the request arriving late and to macOS
  `monotonic()` not advancing during system sleep (which today makes `ends_at` and the in-memory
  countdown disagree after a sleep).
- Applies to any running phase (work *and* break). No-op if already `paused` or `idle`.
- `TimerState` gains `pause_reason: str | None` (in-memory; additive key in `/pomodoro` response;
  resets on resume/stop; not persisted — after a backend restart an auto-pause reads as a plain pause).
- **No auto-resume on wake (decision).** Coming back from lunch and finding the timer silently
  running again would re-create the over-credit problem; resume stays a deliberate action. The menu
  bar shows the reason (e.g. "Work paused (screen off) — 12:30") and already refreshes on wake
  (`menubar.py` `on_wake`). Easy to change to "auto-resume if away < N minutes" later if wanted.
- **Focus-credit fix (Finding 2):** add `session_duration` to `TimerState` /
  `PersistentTimerState` (additive `ALTER TABLE` behind the existing `PRAGMA table_info` pattern),
  set at start and preserved across pause/resume. Completion credits `session_duration` instead of
  `duration_at_start`. Recovery of a pre-existing row with no value falls back to `duration_at_start`.

### 6.5 Tests

- Pause at sleep time: remaining = `ends_at − occurred_at`; `pause_reason == "system_sleep"`;
  no-op when idle/paused; break phase also pauses.
- `/track` with a `system_sleep` event: row stored with client timestamp; timer paused; future or
  stale `occurred_at` is rejected/clamped.
- Aggregation: events at 10:00, sleep at 10:20, wake-app event at 14:00 → laptop time excludes the
  gap after 10:20 (and the pre-sleep gap is still capped at 900s as before). Trailing sleep marker
  on today yields no "now"-based credit.
- Session credit: 25-min session, pause, resume, complete → logged `duration_seconds == 1500`.
- Existing `/activity/summary` and scheduler/email tests remain green after the helper extraction.

### 6.6 Manual verification (can't be unit-tested)

Needs a real machine: (1) close the lid mid-Pomodoro with no external display; (2) let the display
sleep via energy settings with the machine awake; (3) clamshell mode with an external monitor. Confirm
one `system_sleep` row, timer paused with the right remaining time, and first-after-wake app event
present. Which notifications fire in the clamshell case is the part I'm least sure of — verify
rather than assume.

## 7. Repo-convention chores

- `memory.md`: new `GET /focus-load` route, new `DailyActivityRollup` table, `system_sleep` event
  type + optional `occurred_at`, new `pause_reason` / `session_duration` timer fields, and the
  changed startup order (rollup before cleanup).
- `docs/DATA_FLOW.md` (§2 duration logic now lives in one helper; §6 retention/rollup),
  `docs/CODEBASE_GUIDE.md` ("Change how active time is computed" now points at one site),
  `docs/ARCHITECTURE.md` / `docs/DECISIONS.md` (rollup table rationale; "duplicated SQL" rough edge
  resolved; also fix the CLAUDE.md "duplicated in three places" note).
- `PYTHONPATH=backend ./.venv/bin/python -m pytest` passes 100%.
- Vigil/Satan rename: new code uses Satan naming only; no new `VIGIL_*` env vars needed.

## Corrections vs. the original spec

| Original assumption | Reality in this repo | Adjustment |
|---|---|---|
| `focusLoadCalculator.ts`, TypeScript | No TypeScript anywhere | Python module, `pytest` |
| Client-side store (Redux/Zustand/IndexedDB) | `useState` + polling REST only | Server-computed; frontend renders |
| Tailwind / icon set | One hand-written `styles.css`, no icon or chart library | Styles appended to `styles.css`; hand-rolled SVG chart |
| TS/linter/100%-coverage acceptance | No TS, no linter, no JS test runner | `pytest` for math; Vite build + manual UI check |
| Daily focus/laptop minutes are "logged" somewhere | Computed at read time from raw events; raw events purged after 30 days | Shared helper + `DailyActivityRollup` |
| Machine awake ≈ user working | Timer and tracker are sleep-blind | Sleep brake (Section 6) |

## Suggested implementation order

1. `activity.py` shared helper (with the Section 6.3 sleep rule) + refactor `summary.py` /
   `scheduler.py` onto it; existing tests must pass unchanged. *(Checkpoint — smallest reviewable diff.)*
2. `DailyActivityRollup` DDL + startup backfill **before** `cleanup_old_logs`. *(Do this before the next
   backend restart in practice — see Finding 1.)*
3. `focus_load.py` + `tests/test_focus_load.py`.
4. `routes/focus_load.py` + registration + `memory.md`.
5. Sleep brake: `session_duration` fix → `pause_timer` extraction → `/track` `occurred_at` +
   auto-pause → tracker observers → menu bar status text. Tests alongside each step.
6. Full pytest run.
7. Frontend: summary card, then chart, then styles; manual check in the dev server.
8. Manual lid/display-sleep verification (6.6), then docs updates (Section 7).

## Remaining judgment calls (defaults chosen; say if you want them different)

- No auto-resume after wake (Section 6.4).
- Chart window fixed at 28 days; a 8-week toggle is possible later since the rollup will hold more.
- Trend thresholds (±5 points over 7 days) and coaching copy are placeholders to tune once you see it.
- Historical laptop-time over-count in the backfilled 39 days is accepted, not corrected.
