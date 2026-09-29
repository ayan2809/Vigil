# Architecture

> Scope: system-level structure of Satan (formerly "Vigil" — see [DECISIONS.md](DECISIONS.md#1-project-rename-vigil--satan)). For file-by-file navigation see [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md). For request/data lifecycles see [DATA_FLOW.md](DATA_FLOW.md).

## 1. What this system is

Satan is a **local-first, single-user macOS activity tracker, Pomodoro timer, and nightly reflection emailer**. Everything runs on `127.0.0.1`; there is no multi-user auth, no remote deployment target, and no cloud dependency except outbound SMTP for one nightly email.

The whole system exists to answer one question for its one user: *"what did I actually do today, versus what I intended to do?"* — hence the dashboard's own framing as "Intent vs. Reality" (`memory.md` §6.4, `dashboard/src/App.jsx`).

## 2. Components

| Component | Path | Runtime | Responsibility |
|---|---|---|---|
| **Backend API** | `backend/` | Python 3.13, FastAPI + Uvicorn, port `8200` | Single source of truth: SQLite persistence, Pomodoro state machine, SQL aggregation, scheduled jobs, email delivery. |
| **macOS App Tracker** | `trackers/mac_tracker.py` | Python + PyObjC, long-running process | Emits one webhook per foreground-app change and one `system_sleep` per lid-close/display-sleep transition, sourced from OS notifications only. |
| **Browser Extension** | `trackers/browser_extension/` | Chrome/Arc/Brave/Safari MV3 service worker | Emits one webhook per active-tab change; buffers offline. |
| **Menu Bar App** | `menu_bar/menubar.py` | Python + `rumps`, long-running process | Local remote-control + status glance for the Pomodoro timer. |
| **Dashboard** | `dashboard/` | React 18 + Vite SPA, port `3200` (dev) | Human-facing view: timer, task queue, activity heatmap, Focus Load chart (30/60/90D), time breakdown, settings. |
| **LaunchAgents** | `launchd/` | macOS `launchd` plists | Keeps the four long-running processes (server, tracker, menubar, dashboard) alive across login/sleep. |

All five long-running pieces (backend, tracker, browser extension, menubar, dashboard) are **independent OS processes/contexts** that only communicate through the backend's HTTP API. There is no shared memory or IPC beyond HTTP and the SQLite file.

## 3. Runtime architecture

```
 NSWorkspace notifications          Browser tab events
        │                                  │
        ▼                                  ▼
 mac_tracker.py                  browser_extension/background.js
 (ThreadPoolExecutor,                 (chrome.storage.local
  fire-and-forget POST)                offline queue, max 20)
        │                                  │
        └──────────────┬───────────────────┘
                        ▼
              POST http://127.0.0.1:8200/track
                        │
                        ▼
        ┌──────────────────────────────────┐
        │      FastAPI app (satan.main)     │
        │  routes/: tasks, tracking,         │
        │  summary, pomodoro, settings       │
        │  in-process: timer.py, scheduler.py│
        └───────────────┬────────────────────┘
                        │  aiosqlite (WAL)
                        ▼
                data/satan.db
                        ▲
        ┌───────────────┼────────────────────┐
        │               │                    │
  dashboard (3200)  menubar.py         APScheduler jobs
  polls REST API    polls /pomodoro    (nightly reflection,
  on user action     every 5s           outbox processor)
                                              │
                                              ▼
                                     smtplib → SMTP_HOST
                                     (reflection email)
```

Key property: **the backend is the only process that touches the database.** Trackers, the menu bar, and the dashboard are all thin HTTP clients.

## 4. Important abstractions

- **Event-sourced activity log, not a state table.** `TrackingLogs` stores raw point-in-time events (`frontmost_application_changed`, `tab_activated`, `pomodoro_completed`, …). Durations are *never* stored — they're computed on read via SQL `LEAD() OVER (...)` window functions that measure the gap between consecutive events, capped at 900s (15 min) to avoid counting idle/sleep gaps as active time. The SQL lives in `backend/satan/activity.py`, shared by `routes/summary.py`, `scheduler.py`, and `routes/focus_load.py`; finalized days are also persisted in `DailyActivityRollup`. This is the single most important design decision in the codebase — read [DATA_FLOW.md](DATA_FLOW.md#active-time-computation) before touching any time-aggregation code.
- **In-memory timer state + SQLite shadow copy.** `backend/satan/timer.py` holds one process-global `TimerState` dataclass instance (`timer_state`) guarded by an `asyncio.Lock` (`timer_lock`). Every mutation is immediately persisted to the singleton `PersistentTimerState` row (`id = 1`) so a server restart can resume or auto-complete an in-flight Pomodoro. This is *not* a cache — the in-memory object is authoritative while the process is alive; SQLite is the recovery mechanism for when it isn't.
- **Outbox pattern for email.** The nightly reflection generator never calls SMTP directly. It writes a row to `email_outbox` with `is_sent = 0`; a separate 5-minute interval job (`process_email_outbox_job`) is the only code path that calls `smtplib`. This decouples "decide what to send" from "successfully deliver it," and is what makes the misfire/backfill resilience in §6 possible.
- **Zero-polling event sourcing on the tracker side.** `mac_tracker.py` deliberately does not poll `NSWorkspace.frontmostApplication` on a timer; it registers KVO + `NSWorkspaceDidActivateApplicationNotification` and reacts only to OS-pushed events. This is a documented, enforced architectural rule (`.agents/AGENTS.md` Rule 4) — do not add a polling loop here.
- **Singleton-row settings/timer tables.** `user_settings` and `PersistentTimerState` both use `CHECK (id = 1)` to enforce exactly one row via `INSERT ... ON CONFLICT(id) DO UPDATE`. There is no multi-user concept anywhere in the schema.

## 5. External dependencies

| Dependency | Used by | Purpose | Failure mode |
|---|---|---|---|
| macOS `NSWorkspace` (PyObjC/Cocoa) | `trackers/mac_tracker.py` | Foreground-app change notifications | Tracker process must run on macOS; wrapped in `try/except` per-callback so one bad event can't crash the Cocoa run loop. |
| macOS `say` binary | `backend/satan/audio.py` | Spoken Pomodoro phase-change announcements | Fire-and-forget `subprocess.Popen`; failure is logged, never raised. |
| Chrome/Arc/Brave/Safari extension APIs | `trackers/browser_extension/` | Active-tab tracking | Browser-side only; backend has no dependency on it being installed. |
| SMTP server (Gmail by default) | `backend/satan/scheduler.py` | Nightly reflection email delivery | If `SMTP_HOST` unset or send fails, the row stays `is_sent = 0` in `email_outbox` and is retried every 5 minutes indefinitely — no data is lost. |
| `launchd` | `launchd/*.plist` | Process supervision (auto-restart, run-at-login) | Optional; all four processes can be run manually from a terminal per the README. |

## 6. Architectural constraints (do not violate)

These are enforced by `.agents/AGENTS.md` and cross-checked against the code — they are load-bearing, not stylistic:

1. **No polling for activity detection.** Trackers react to OS/browser events only (Rule 4). Confirmed in `mac_tracker.py` (KVO-based) and `background.js` (listener-based).
2. **No blocking I/O on UI/event-loop threads.** `mac_tracker.py` and `menubar.py` dispatch every HTTP call through a `ThreadPoolExecutor`; FastAPI handlers are `async`. Confirmed in all three files.
3. **All backend DB access goes through `get_db()`** (`backend/satan/db.py`), which sets `PRAGMA busy_timeout = 5000`, `journal_mode = WAL`, and `foreign_keys = ON` on every connection. Confirmed as the sole connection path used by every route and job.
4. **API response shapes are a contract.** Dashboard, menu bar, and trackers all hard-code JSON key names (e.g. `remaining_seconds`, `totalSeconds`, `apps`). Renaming a response key breaks at least one other component silently (no shared type definitions exist between backend and clients).
5. **`memory.md` must be kept in sync with schema/route/env changes** — this is a repository-level rule from the agents themselves, not just for this doc set. `memory.md` and this `docs/` tree should be treated as one system: `memory.md` is the fast/quick reference, `docs/` is the deep reference.
6. **No `print()` in `backend/`, `trackers/`, `menu_bar/`.** All logging goes through `satan.logger.setup_logger`, writing rotating files into `data/`.

## Open questions / uncertain areas

- **Dashboard production serving is undocumented.** `dashboard/dist/` exists (a built artifact) and `launchd/com.satan.dashboard.plist` runs `npm run dev`, i.e. the Vite *dev* server is what's kept alive in production via LaunchAgent — there's no evidence of a static file server or reverse proxy for the built `dist/`. This may be intentional (single-user, local-only tool) but is worth confirming before assuming a "build" step matters operationally.
- **CORS allows `chrome-extension://.*` and `safari-web-extension://.*` unconditionally** (`backend/satan/main.py`) — i.e., *any* installed extension with that origin pattern, not just this repo's own extension ID, can POST to `/track`. This is presumably acceptable given the local-only, single-user threat model, but it's not access-controlled beyond binding to `127.0.0.1`.
