# CLAUDE.md

Satan (formerly "Vigil") is a local-first, single-user macOS activity tracker + Pomodoro timer + nightly reflection emailer. Everything runs on `127.0.0.1`; no auth, no multi-user, no cloud deps except outbound SMTP for one daily email.

**Read `memory.md` first** — it's the actively-maintained, fast-reference schema/API/env blueprint for this repo, kept in sync by convention on every change. This file (`CLAUDE.md`) is the entry point; `docs/` holds the deeper narrative reference:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, runtime diagram, abstractions, constraints
- [`docs/CODEBASE_GUIDE.md`](docs/CODEBASE_GUIDE.md) — repo layout, "where to make change X"
- [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) — ingest → aggregation → Pomodoro → email lifecycles
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — build/run/test/debug commands
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — why things are shaped this way, with confirmed-vs-inferred rationale
- [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — domain terms (Vigil vs Satan, outbox pattern, active/focus time, etc.)

## Repository architecture summary

Five independent processes communicating only over HTTP + a shared SQLite file:

- **Backend** (`backend/`, FastAPI/Uvicorn, port `8200`) — the only process that touches `data/satan.db`. Routes in `backend/satan/routes/`; Pomodoro state machine in `backend/satan/timer.py`; nightly email + outbox jobs in `backend/satan/scheduler.py`.
- **macOS tracker** (`trackers/mac_tracker.py`) — PyObjC/`NSWorkspace`, event-driven only (no polling), POSTs to `/track`.
- **Browser extension** (`trackers/browser_extension/`) — MV3, POSTs to `/track`, buffers up to 20 events offline.
- **Menu bar app** (`menu_bar/menubar.py`) — `rumps`, polls `/pomodoro` every 5s.
- **Dashboard** (`dashboard/`, React + Vite, port `3200` dev) — single-file UI in `dashboard/src/App.jsx`.

Activity is event-sourced: `TrackingLogs` stores raw timestamped events; durations are computed at read time via SQL `LEAD() OVER (...)` window functions (capped at 900s per gap), implemented once in `backend/satan/activity.py` and shared by `routes/summary.py`, `scheduler.py`, and `routes/focus_load.py`. Finalized days are persisted in `DailyActivityRollup` so Focus Load history survives the 30-day log purge. See [DATA_FLOW.md](docs/DATA_FLOW.md).

## Conventions and critical constraints (enforced by `.agents/AGENTS.md` — read it in full before backend work)

1. **No polling for activity detection.** Trackers react only to OS/browser events. Never add a timer-based "check current app" loop.
2. **No blocking I/O on event-loop/UI threads.** Tracker and menu bar HTTP calls go through a `ThreadPoolExecutor`; FastAPI handlers are `async`.
3. **All DB access via `get_db()`** (`backend/satan/db.py`) — WAL mode, `busy_timeout=5000`, parameterized queries always.
4. **Zero `print()`** in `backend/`, `trackers/`, `menu_bar/` — use `satan.logger.setup_logger` / the shared `logger`.
5. **API response shapes are a contract** — dashboard, menu bar, and trackers hardcode JSON keys with no shared schema. Don't rename/retype an existing response field without updating every consumer.
6. **Pomodoro state mutations** must happen inside `async with timer_lock:` and be followed by `await save_timer_state(db)`.
7. **Run the test suite after any backend/route/model/schema change**, and it must pass 100%:
   ```zsh
   PYTHONPATH=backend ./.venv/bin/python -m pytest
   ```
   (`pytest.ini` limits collection to `tests/`, and the root `conftest.py` ignores the `test_smtp*.py` scratch scripts, which hit SMTP at import.)
8. **Update `memory.md`** whenever you change API endpoints, DB schema, env vars, or background jobs — this is a repo rule, not optional cleanup.
9. **Vigil → Satan rename is still in progress.** Several places intentionally support both names (`SATAN_*` env vars falling back to `VIGIL_*`, `data/vigil.db` → `data/satan.db` one-time copy, dashboard package still named `vigil-dashboard`). Preserve the dual-read fallback pattern rather than deleting the legacy branch, unless explicitly asked to finish the rename.

## Commands

```zsh
# Setup
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
npm --prefix dashboard install

# Run (each in its own terminal)
PYTHONPATH=backend ./.venv/bin/python backend/server.py   # API :8200, docs at /docs
./.venv/bin/python trackers/mac_tracker.py
./.venv/bin/python menu_bar/menubar.py
npm --prefix dashboard run dev                              # dashboard :3200

# Test
PYTHONPATH=backend ./.venv/bin/python -m pytest
```

No CI/CD exists in this repo — test verification is manual.

## Important files to inspect before non-trivial changes

- `backend/satan/db.py` — schema DDL + migrations (additive `ALTER TABLE` behind `PRAGMA table_info` checks, not a migration framework)
- `backend/satan/timer.py` — Pomodoro state machine; in-memory `timer_state` is authoritative while the process runs, `PersistentTimerState` is recovery-only
- `backend/satan/scheduler.py` — nightly reflection generation + outbox delivery, with sleep-resilient `misfire_grace_time`/backfill logic
- `dashboard/src/App.jsx` — the entire frontend (no per-feature file split)
- `.agents/AGENTS.md` — the authoritative rules document for agents working in this repo
- `memory.md` — current schema/API/env snapshot

## Known rough edges (see docs/DECISIONS.md and docs/ARCHITECTURE.md for detail)

- The active-time SQL lives only in `backend/satan/activity.py`. Note `strftime('now','localtime')` in the "today's last event" branch is compared against a UTC epoch, so in timezones east of UTC that event is always credited the full 900s cap (pre-existing; not changed).
- `data/`, `.env`, and two untracked root-level scripts (`test_smtp.py`, `test_smtp_noauth.py`) contain a real SMTP credential in plaintext on disk — not committed (gitignored/untracked), but present in the working tree.
- Backend assumes a single Uvicorn worker (`timer_state` is a module-level singleton); do not add `workers > 1` without redesigning Pomodoro state sharing.
