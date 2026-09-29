# Data Flow

> How data enters, moves through, and leaves the system. See [ARCHITECTURE.md](ARCHITECTURE.md) for component responsibilities.

## 1. Activity tracking flow (ingest)

```
macOS foreground-app change          Browser active-tab change
        │                                    │
mac_tracker.py:                     background.js:
  WorkspaceObserver.emit_application   reportActiveTab()
  (dedup via last_process_id)          (dedup via lastSignature string)
        │                                    │
        ▼                                    ▼
  POST /track { source, application_name,   POST /track { source: "browser",
    event_type: "frontmost_application_       application_name: <browser name>,
    changed", metadata: {bundle_id,           url, title,
    process_id} }                             event_type: "tab_activated" |
                                               "tab_updated" | "window_focused" |
                                               "history_state_updated",
                                               metadata: {tab_id, window_id} }
```

- **Endpoint:** `POST /track` (`backend/satan/routes/tracking.py`), validated against `TrackingEvent` (`backend/satan/models.py`).
- **Transformation:** the handler parses `url` with `urlparse` to extract `domain` server-side (clients never send domain directly). It stamps `occurred_at` (offset-aware local ISO) and `local_date` (`YYYY-MM-DD`) using `local_now()` at receipt time — **not** whatever time the client claims. The one exception is `system_sleep` (below): its client-supplied `occurred_at` is honored if it is not in the future and at most 24h old, because the request can be delayed until after wake.
- **Storage:** one row per event in `TrackingLogs`. No deduplication happens server-side; both tracker clients dedupe locally before sending (`last_process_id` in `mac_tracker.py`, `lastSignature` in `background.js`).
- **Offline resilience:** the browser extension buffers up to 20 events in `chrome.storage.local` (`offlineQueue`) when the backend is unreachable, flushing oldest-first on the next successful send (`background.js::flushQueue`). `mac_tracker.py` has no such queue — a webhook failure while the backend is down is simply logged and dropped (there's no retry or local buffer for the macOS tracker).
- **Sleep/lid/display events:** `mac_tracker.py` observes `NSWorkspace` WillSleep/DidWake and ScreensDidSleep/ScreensDidWake (pushed by macOS, no polling). Entering "away" (system asleep *or* display asleep) emits exactly one `system_sleep` event with a client `occurred_at`; leaving it clears the tracker's `last_process_id` dedup and re-emits the frontmost app (the foreground app is unchanged across sleep, so it would otherwise be swallowed). On receipt of `system_sleep`, `/track` also calls `pause_running_timer(at=<sleep time>, reason="system_sleep")` — see §3.
- **Special event type:** `pomodoro_completed` is *not* sent by a tracker — it's inserted directly by the backend itself (`backend/satan/timer.py::finish_phase_after`) when a work phase ends, with `metadata_json` carrying `{task_id, duration_seconds}`. This is how focus time is distinguished from laptop time downstream.

## 2. Active time computation (read path)

This is the core transformation in the system. The SQL now lives in one module, `backend/satan/activity.py` (`get_app_durations`, `get_daily_activity_records`), called by `routes/summary.py`, `scheduler.py`, and `routes/focus_load.py`.

**Input:** raw `TrackingLogs` rows for a date (or date range), excluding `event_type = 'pomodoro_completed'` and excluding ignored system processes (`loginwindow`, `ScreenSaverEngine`).

**Transformation (SQL window function):**
1. For each event, `LEAD(occurred_at) OVER (ORDER BY occurred_at ASC)` finds the *next* event's timestamp.
2. Duration for that event = `next_occurred_at - occurred_at`, **capped at 900 seconds (15 minutes)** — this cap is what prevents a laptop left open overnight from counting as 8 hours of "active" time.
3. For the *last* event of *today specifically* (no next event yet), duration is computed against `now` instead, still capped at 900s. For the last event on a *past* day with no successor, a flat fallback of 60s is used (there is no "now" to compare against).
4. `system_sleep` events (emitted by `mac_tracker.py` when the lid closes or the display sleeps) stay in the window but are assigned 0 duration, so time between sleep and the next event is never counted.
5. Rows are grouped by `app_name` (and `domain` for browser events) and summed.

**Outputs:**
- `GET /active-time-summary?date=YYYY-MM-DD` → `{"totalSeconds": int, "apps": [{"name", "source", "seconds", "domains": [{"domain", "seconds"}]}]}` — used by the dashboard's "Time breakdown" panel.
- `GET /activity/summary?days=28` → `{"days": [{"date", "event_count", "total_laptop_time_seconds", "total_focus_time_seconds"}]}` — used by the dashboard's 28-day heatmap. Focus time here is summed from `pomodoro_completed` rows' `metadata_json.duration_seconds` (defaulting to 1500s/25min if absent), *not* from the same window-function computation as laptop time.
- `scheduler.py::generate_nightly_reflection_payload` builds the nightly email from the same helper, so the email and dashboard numbers share one implementation.
- `GET /focus-load?days=30|60|90` derives acute (7-day, includes today) and chronic (28-day) focus load from per-day totals (`get_daily_totals`): finalized days from `DailyActivityRollup`, today live. `days` (7–180, default 30) only sets the chart `history` window (trimmed to days since first data); the headline numbers always describe now. Math lives in the pure `backend/satan/focus_load.py`.

## 3. Pomodoro timer flow

```
Client (dashboard / menu bar)
   │  POST /pomodoro/start {task_id?, duration_seconds}
   ▼
routes/pomodoro.py: acquire timer_lock → mutate timer_state (in-memory)
   │                → save_timer_state(db) → PersistentTimerState row (id=1)
   │                → schedule_phase_completion() → asyncio.create_task(finish_phase_after)
   │                → optionally mark the task 'in_progress' in PomodoroTasks
   ▼
finish_phase_after() sleeps for the phase duration, then on completion:
   - if phase was "work": increments task.completed_pomodoros, inserts a
     TrackingLogs row (event_type='pomodoro_completed'), flips to "break" phase,
     re-persists state, re-schedules completion for the break duration,
     and calls audio.announce("Work interval complete. Take a break.")
   - if phase was "break": resets timer_state to idle, re-persists,
     announces "Break complete. Your next Pomodoro is ready."
```

- **Pause paths:** manual `POST /pomodoro/pause` and the sleep auto-pause both go through `timer.py::pause_running_timer` (caller holds `timer_lock`). Manual pauses measure elapsed time with the monotonic clock; auto-pauses compute remaining time from wall-clock `ends_at` minus the sleep moment (macOS's monotonic clock doesn't advance during system sleep, and the sleep request may arrive after wake). A sleep timestamp before the current run started, or after it ended, is ignored. `pause_reason` (`manual` / `system_sleep`) is exposed on `/pomodoro`; there is **no auto-resume** on wake.
- **Focus credit:** `TimerState.session_duration` (persisted in `PersistentTimerState.session_duration`) holds the planned phase length and survives pause/resume, so a resumed Pomodoro is credited its full duration. (`duration_at_start` is reset on pause and set to the remaining time on resume, so it can't be used for credit.)
- **Snapshot reads** (`GET /pomodoro`) compute `remaining_seconds` live by subtracting elapsed wall-clock time (via `time.monotonic()`) from the stored duration — the persisted `remaining_seconds` column is a fallback for recovery, not the live truth while the process is running.
- **Crash/restart recovery:** on server startup, `load_persisted_timer_state()` reads the single `PersistentTimerState` row. If it was `running`, it recomputes remaining time from `ends_at - now`; if that's ≤ 0, it immediately finishes the phase (handles "laptop was asleep through an entire Pomodoro"). If it was `paused`, it restores `remaining_seconds` as-is.
- **Consumers:** the dashboard polls this on load and re-renders a local countdown (`App.jsx` `setInterval`, resynced from `duration_at_start`/`started_at` rather than polling every second); the menu bar polls `GET /pomodoro` every 5 seconds (`@rumps.timer(5)`) and on macOS wake (`@rumps.events.on_wake`).

## 4. Settings flow

```
Dashboard Settings modal (App.jsx)
   │ textarea (one goal/value per line) → split("\n") → array
   ▼
PUT /settings { pomodoro_duration_minutes, sleep_time, reflection_email,
                monthly_goals: [...], core_values: [...] }
   ▼
routes/settings.py::update_settings
   - merges only the fields present (exclude_unset)
   - monthly_goals array is the source of truth; monthly_goal (singular,
     legacy) is derived as monthly_goals[0] and kept in sync for old clients
   - re-serializes both lists to JSON text columns
   - if sleep_time changed, calls scheduler.update_nightly_job_trigger()
     to reschedule the nightly email job's cron trigger immediately
   ▼
user_settings row (id=1) updated; UPDATE response echoed back to client
```

- **Migration/back-compat detail:** `monthly_goal` (a single string, legacy) and `monthly_goals` (a JSON array, current) both exist as columns. Reads always prefer `monthly_goals`; `monthly_goal` is kept populated as `monthly_goals[0]` for any consumer still reading the singular field. See `git log` commit `eb887a6` ("Support multiple monthly focus goals...").

## 5. Nightly reflection email flow (outbox pattern)

```
APScheduler cron job "generate_nightly_reflection"
  (fires daily at sleep_time - 15 minutes; misfire_grace_time=3600, coalesce=True)
        │
        ▼
generate_nightly_reflection_job()
  - skip if email_outbox already has a row for today
  - call generate_nightly_reflection_payload(today)
      - runs the active-time SQL (see §2) + focus-time SQL for today
      - CRITICAL RULE: if total_laptop_time == 0, return None → no row is written
      - else build WatchOS-style subject/body (top-3 apps by time, medal emoji)
        ▼
  INSERT INTO email_outbox (target_date, subject, body, is_sent=0, created_at)

APScheduler interval job "process_email_outbox" (every 5 minutes,
  misfire_grace_time=3600, coalesce=True)
        │
        ▼
process_email_outbox_job()
  - reads user_settings.reflection_email; if unset, no-op (email stays queued)
  - selects all email_outbox WHERE is_sent = 0
  - for each: builds a MIMEText message, connects via smtplib.SMTP + STARTTLS,
    optionally authenticates (SMTP_USER/SMTP_PASSWORD from .env), sends
  - on success: UPDATE is_sent=1, sent_at=now
  - on failure: logs and breaks out of the loop (stops processing further
    rows this cycle, to avoid hammering a down/misconfigured SMTP server;
    retried again on the next 5-minute tick)

On every server startup (satan.main lifespan → scheduler.start_scheduler):
  check_and_backfill_missing_reflections(lookback_days=7)
    - for each of the past 7 days, if no email_outbox row exists yet,
      regenerate the payload and enqueue it (handles "laptop was off
      when the nightly job should have fired")
  → then immediately calls process_email_outbox_job() once, so any
    backfilled or previously-stuck emails go out right away rather than
    waiting up to 5 minutes.
```

**External system touched:** SMTP server configured via `.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`). Default `.env.example` targets `smtp.gmail.com:587`, which requires a Google App Password (not a regular account password) for `SMTP_PASSWORD`.

## 6. Data retention

On every server startup, `rollup_past_days` first persists per-day laptop/focus totals into `DailyActivityRollup`; then `cleanup_old_logs(retention_days=30)` (`backend/satan/db.py`) deletes `TrackingLogs` rows where `local_date` is older than 30 days (skipped for that startup if the rollup fails). The rollup table is never pruned, so Focus Load history outlives the raw logs. This is the only automatic data deletion in the system — `PomodoroTasks`, `email_outbox`, and `user_settings` are never pruned.

## Open questions / uncertain areas

- **Why does the "last event with no successor" fallback differ between today (compare-to-now) and past days (flat 60s)?** This is confirmed behavior in the SQL (`WHEN ? = ? THEN ... ELSE 60`), but the *rationale* for the specific 60s constant for stale trailing events on past days is not documented anywhere — inferred to be "assume a minimal engagement rather than zero, without inventing an arbitrary large number."
- **No confirmed reconciliation** between the dashboard's per-day focus-time figure (`activity/summary`, derived from `pomodoro_completed` metadata) and a scenario where a Pomodoro's `duration_seconds` metadata is missing — it silently defaults to 1500s (25 min) via `COALESCE(..., 1500)` in three separate SQL statements. If the default work duration is changed via settings, historical rows keep whatever was true when they were recorded (this is correct/intended, just noting it's not a live-recomputed value).
