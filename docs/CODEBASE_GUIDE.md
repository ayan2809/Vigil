# Codebase Guide

> Where things live, and where to make changes. See [ARCHITECTURE.md](ARCHITECTURE.md) for why the system is shaped this way.

## Repository layout

```
Satan/  (directory on disk is still named "Vigil" — see DECISIONS.md)
├── backend/
│   ├── server.py                # Uvicorn entry point
│   └── satan/
│       ├── main.py              # FastAPI app factory, lifespan, CORS, router registration
│       ├── db.py                # Connection lifecycle, schema DDL, migrations, retention cleanup
│       ├── timer.py             # Pomodoro state machine (in-memory + persisted), `pause_running_timer`
│       ├── activity.py          # Shared active-time SQL + DailyActivityRollup helpers
│       ├── focus_load.py        # Pure Focus Load math (acute/chronic, classification, history)
│       ├── scheduler.py         # APScheduler jobs: nightly reflection + outbox processor
│       ├── models.py            # Pydantic request/response models + TimerState dataclass
│       ├── logger.py            # Rotating file logger factory
│       ├── audio.py             # macOS `say` TTS wrapper
│       └── routes/
│           ├── tasks.py         # /tasks CRUD
│           ├── tracking.py      # /track webhook receiver
│           ├── summary.py       # /active-time-summary, /activity/summary (thin; SQL in activity.py)
│           ├── focus_load.py    # /focus-load (?days=30|60|90 chart window)
│           ├── pomodoro.py      # /pomodoro/* lifecycle
│           └── settings.py      # /settings GET/PUT
├── trackers/
│   ├── mac_tracker.py           # Standalone PyObjC process
│   └── browser_extension/
│       ├── manifest.json        # MV3 manifest
│       └── background.js        # Service worker: tab tracking + offline queue
├── menu_bar/
│   └── menubar.py                # Standalone `rumps` process
├── dashboard/
│   ├── src/App.jsx               # Entire UI in one component tree
│   ├── src/main.jsx              # React root mount
│   ├── src/styles.css            # All styling (no CSS framework)
│   └── dist/                     # Built output (checked in; see ARCHITECTURE.md open question)
├── launchd/
│   ├── install_agents.sh         # Generates + writes 4 plists to ~/Library/LaunchAgents
│   └── com.satan.*.plist         # Static templates (install_agents.sh regenerates these dynamically)
├── tests/
│   ├── test_api.py               # Tasks, tracking, summary, Pomodoro lifecycle/recovery
│   ├── test_focus_load.py        # Pure Focus Load math
│   ├── test_sleep_and_rollup.py  # Sleep brake, aggregation rule, rollup, /focus-load
│   └── test_settings_and_outbox.py # Settings API, outbox generation, WatchOS formatting
├── data/                          # Runtime SQLite DBs + rotating logs (gitignored except .gitkeep)
├── memory.md                      # Living architecture/schema/API blueprint — READ FIRST, keep in sync
├── .agents/AGENTS.md              # Mandatory rules for AI agents working in this repo
└── requirements.txt / pytest.ini (testpaths=tests) / conftest.py (ignores test_smtp*.py) / .env(.example)
```

## Entry points

| To run... | Entry point | Command |
|---|---|---|
| Backend API | `backend/server.py` | `PYTHONPATH=backend ./.venv/bin/python backend/server.py` |
| macOS tracker | `trackers/mac_tracker.py` | `./.venv/bin/python trackers/mac_tracker.py` |
| Menu bar app | `menu_bar/menubar.py` | `./.venv/bin/python menu_bar/menubar.py` |
| Dashboard (dev) | `dashboard/` (Vite) | `npm --prefix dashboard run dev` |
| Test suite | `tests/` | `PYTHONPATH=backend ./.venv/bin/python -m pytest` |

`backend/satan/main.py:app` is the FastAPI ASGI app object if you need to import it directly (tests do this via `httpx.ASGITransport`).

## Where to make common changes

| Task | Files to touch |
|---|---|
| Add/change an API endpoint | New or existing file in `backend/satan/routes/`, registered in `backend/satan/main.py` via `app.include_router(...)`. Add/extend a Pydantic model in `backend/satan/models.py`. **Update `memory.md` §5 API table.** |
| Change database schema | `backend/satan/db.py::initialize_database()` — add `CREATE TABLE IF NOT EXISTS` and, for existing tables, an `ALTER TABLE ... ADD COLUMN` guarded by a `PRAGMA table_info` check (see the `monthly_goal`/`monthly_goals`/`core_values` migration pattern already there). **Update `memory.md` §4 schema section.** |
| Change Pomodoro behavior | `backend/satan/timer.py` (state machine) and `backend/satan/routes/pomodoro.py` (HTTP surface). Remember: every state mutation must happen inside `async with timer_lock:` and be followed by `await save_timer_state(db)`. |
| Change nightly email content/timing | `backend/satan/scheduler.py`. Subject/body formatting is in `generate_nightly_reflection_payload()`; scheduling math is in `parse_sleep_time_to_trigger()`; delivery is in `process_email_outbox_job()`. |
| Change how "active time" is computed | Edit `backend/satan/activity.py` — the single shared home of the `LEAD() OVER (...)` SQL (900-second cap, ignored-app list, `system_sleep` terminator rule). `routes/summary.py`, `scheduler.py`, and `routes/focus_load.py` all call it. Rollups of finalized days (`DailyActivityRollup`) are written from the same helper. |
| Change Focus Load math, thresholds, or chart data | `backend/satan/focus_load.py` (pure, unit-tested in `tests/test_focus_load.py`) and `backend/satan/routes/focus_load.py`. Chart rendering (inline SVG, hover readout, 30/60/90D toggle) is `FocusLoadChart` / `FocusLoadCard` in `App.jsx`; the copy strings are `LOAD_COPY` / `TREND_COPY` there. Update `memory.md` §5 if the response shape changes. |
| Change sleep/lid/display behavior | Tracker: `WorkspaceObserver` sleep/wake handlers in `trackers/mac_tracker.py` (emit `system_sleep`). Backend: `routes/tracking.py` (honors client `occurred_at` for that event only, then auto-pauses) and `timer.py::pause_running_timer`. Aggregation rule: `_DURATION_EXPR` in `activity.py`. |
| Add a foreground-app ignore rule (e.g. new screensaver process) | `IGNORED_BUNDLE_IDS` / `IGNORED_APP_NAMES` in `trackers/mac_tracker.py`, and the matching `COALESCE(application_name, '') NOT IN (...)` clause in the SQL queries above. |
| Change dashboard UI | Everything is in `dashboard/src/App.jsx` (single file, ~850 lines) plus `dashboard/src/styles.css`. There is no component-file-per-feature convention — small presentational components (`MonthlyGoalBanner`, `DailyValues`, `FocusLoadCard`, `FocusLoadChart`, `RangeToggle`) are defined inline above `App`. Layout order: timer + laptop time, Focus queue (full width), goal banner, activity heatmap, Focus Load card, then Daily rules + Time breakdown. |
| Change Settings shape | Backend: `backend/satan/models.py::UserSettings`/`SettingsUpdate` + `backend/satan/routes/settings.py`. Frontend: `settingsForm` state and the settings modal JSX in `App.jsx`. Both must stay in sync since there's no shared schema. |
| Add a new environment variable | Read it in the relevant module with `os.environ.get("SATAN_X", os.environ.get("VIGIL_X", default))` — the double-lookup (`SATAN_*` then legacy `VIGIL_*`) is the established pattern during the rename transition (see DECISIONS.md). Document it in `.env.example` and `memory.md` §3. |
| Add a background scheduled job | `backend/satan/scheduler.py::start_scheduler()` — register with `scheduler.add_job(..., misfire_grace_time=3600, coalesce=True)` to stay consistent with the sleep-resilience pattern used by the two existing jobs. |
| Run/verify a change | Always run `PYTHONPATH=backend ./.venv/bin/python -m pytest` before considering backend work done (`.agents/AGENTS.md` Rule 6). |

## Common patterns in this repository

- **Request-scoped DB connections.** Every route depends on `db: aiosqlite.Connection = Depends(get_db)`; nothing holds a connection across requests. Background jobs instead do `async for db in get_db(): ...` (an async-generator-as-context-manager idiom used throughout `scheduler.py` and `timer.py`).
- **404 helper functions.** Each router with a single-resource `{id}` path defines a small `get_x_or_404(db, id)` helper (see `routes/tasks.py::get_task_or_404`) reused by GET/PATCH/DELETE.
- **`exclude_unset=True` for partial updates.** `TaskUpdate`, `SettingsUpdate` PATCH/PUT handlers call `payload.model_dump(exclude_unset=True)` so omitted fields don't overwrite existing values.
- **Fire-and-forget side effects.** TTS announcements (`audio.announce`) and webhook posts from trackers are never awaited for completion by the caller — they're either `subprocess.Popen` (no wait) or submitted to a `ThreadPoolExecutor` (no `.result()` call).
- **Dual env var naming during rename.** Several modules check `SATAN_*` first, falling back to `VIGIL_*` (e.g. `backend/satan/models.py`, `trackers/mac_tracker.py`, `menu_bar/menubar.py`). This is a backward-compatibility shim from the `Vigil → Satan` rename commit — see [DECISIONS.md](DECISIONS.md).
- **All timestamps are offset-aware local time**, not UTC. `local_now()` / `iso_now()` in `db.py` are the only sanctioned way to get a timestamp; do not use `datetime.utcnow()` or naive `datetime.now()` elsewhere.

## Navigation tips for future sessions

- Start with `memory.md` for a fast, current schema/API/env snapshot — it's actively maintained per repo rules and is usually more current than any doc here for line-level details.
- `backend/satan/routes/*.py` files are short (< 150 lines each) and self-contained — read the whole file rather than grepping, it's faster.
- The active-time SQL now lives only in `backend/satan/activity.py`; finalized days are frozen into `DailyActivityRollup`, so changing the duration logic does not retroactively change already-rolled-up days.
- There is no ORM, no migrations framework, and no shared frontend/backend type layer — schema and contract changes are manual and must be cross-checked by hand.
