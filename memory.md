# Satan Project Memory

## 1. Project Overview & Philosophy

**Satan** is a lightweight, local-first macOS background activity tracker, Pomodoro timer engine, and daily reflection system built with a **zero-polling event-driven architecture**:

- **No Tracker Polling Loops**: Foreground application switches and browser active-tab changes are delivered exclusively via macOS operating system event notifications (`NSWorkspace` KVO/notifications) and browser WebExtension tab event listeners.
- **Local-First & Privacy Preserving**: All activity logs, task state, timer persistence, and settings remain local on the user's machine in an async SQLite database (`data/satan.db`).
- **WatchOS-Optimized Nightly Reflections**: Automatically aggregates daily active screen time and Pomodoro focus metrics into a minimal, watch-friendly email outbox payload delivered near sleep time.

---

## 2. Architecture Overview & Module Index

Satan is structured as a decoupled, multi-component system:

```
Satan/
├── backend/                  # FastAPI Application Package
│   ├── server.py             # Uvicorn entry point (PYTHONPATH=backend)
│   └── satan/
│       ├── main.py           # App factory, CORS, lifespan startup/shutdown
│       ├── db.py             # Async SQLite lifecycle (WAL mode, busy_timeout=5000)
│       ├── timer.py          # Persistent Pomodoro state machine & timer lock
│       ├── scheduler.py      # APScheduler jobs for nightly reflection outbox & email queue
│       ├── models.py         # Pydantic schemas and dataclasses
│       ├── logger.py         # Structured rotating file logging setup
│       ├── audio.py          # Native macOS speech synthesis via asynchronous `say`
│       └── routes/           # Decoupled API routers
│           ├── tasks.py      # Task CRUD operations (`/tasks`)
│           ├── tracking.py   # Activity webhook receiver (`/track`)
│           ├── summary.py    # Duration calculation SQL aggregations (`/summary/*`)
│           ├── pomodoro.py   # Pomodoro lifecycle controls (`/pomodoro/*`)
│           └── settings.py   # User configuration management (`/settings`)
├── trackers/
│   ├── mac_tracker.py        # PyObjC NSWorkspace observer for macOS app activity
│   └── browser_extension/    # Manifest V3 extension with offline queue for Chrome/Arc/Brave
├── menu_bar/
│   └── menubar.py            # Rumps macOS status bar app with background thread I/O
├── dashboard/                # Vite + React single-page dashboard (Port 3200)
│   └── src/
│       ├── App.jsx           # Main UI container (heatmap, timeline, tasks, timer)
│       ├── main.jsx          # React entry point
│       └── styles.css        # Dashboard styling system
├── launchd/                  # macOS LaunchAgent automation
│   ├── install_agents.sh     # Plist generator & launchctl bootstrapper
│   └── com.satan.*.plist     # LaunchAgent templates for server, tracker, menubar, dashboard
├── data/                     # Local SQLite database and rotating log directory
├── tests/                    # Automated pytest integration & unit test suite
│   ├── test_api.py           # API endpoints, CRUD, and state recovery tests
│   └── test_settings_and_outbox.py # Settings API & email outbox tests
└── memory.md                 # System memory and architectural blueprint
```

---

## 3. Technology Stack, Ports & Configuration

### Tech Stack

| Domain | Technology | Key Libraries |
| --- | --- | --- |
| **Backend API** | Python 3.13 / FastAPI | `uvicorn`, `aiosqlite`, `apscheduler`, `pydantic` |
| **macOS Tracker** | PyObjC / AppKit | `NSWorkspace`, `PyObjCTools.AppHelper` |
| **Browser Extension** | WebExtensions Manifest V3 | `chrome.storage.local`, `chrome.tabs`, `chrome.windows` |
| **Menu Bar Controls** | Python / Rumps | `rumps`, `urllib.request` |
| **Dashboard** | React.js / Vite | `lucide-react`, `tailwindcss` / vanilla CSS |
| **Service Execution** | macOS `launchd` | `launchctl`, LaunchAgents |

### Network Ports & Base URLs

- **Backend API Server**: `http://127.0.0.1:8200` (Swagger docs at `/docs`)
- **React Dashboard**: `http://127.0.0.1:3200`

### Environment Variables

| Variable | Default Value | Description |
| --- | --- | --- |
| `SATAN_DB_PATH` | `data/satan.db` | Absolute or relative path to SQLite database file |
| `SATAN_WORK_SECONDS` | `1500` (25m) | Fallback work duration for Pomodoro sessions |
| `SATAN_BREAK_SECONDS` | `300` (5m) | Break duration following completed work session |
| `SATAN_TRACK_URL` | `http://127.0.0.1:8200/track` | Target webhook URL for app and browser trackers |
| `SATAN_API_URL` | `http://127.0.0.1:8200` | Base API URL consumed by menu bar and dashboard |
| `SMTP_HOST` | `""` | SMTP server host for sending reflection emails |
| `SMTP_PORT` | `587` | SMTP server port |
| `SMTP_USER` | `""` | SMTP authentication username |
| `SMTP_PASSWORD` | `""` | SMTP authentication password |
| `SMTP_FROM` | `""` | From address header for outbox email sender |

---

## 4. Database Schema & Data Model

Satan uses an **async SQLite database (`aiosqlite`)** operating with:
- **Journal Mode**: `WAL` (Write-Ahead Logging for concurrent read/write throughput)
- **Busy Timeout**: `PRAGMA busy_timeout = 5000;` (5-second timeout for lock acquisition)
- **Foreign Keys**: `PRAGMA foreign_keys = ON;`
- **Automatic Data Retention**: Startup hook `cleanup_old_logs(30)` purges tracking records older than 30 days.

### Tables & Schemas

#### 1. `TrackingLogs`
Stores raw event-sourced activity webhooks from macOS apps and browser extensions.

```sql
CREATE TABLE IF NOT EXISTS TrackingLogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,         -- ISO-8601 offset timestamp (e.g. 2026-07-24T15:30:00+05:30)
    local_date TEXT NOT NULL,          -- YYYY-MM-DD local date
    source TEXT NOT NULL CHECK (source IN ('browser', 'app')),
    application_name TEXT,             -- e.g. "Arc", "Visual Studio Code", "Terminal"
    url TEXT,                          -- Web page URL (browser events)
    domain TEXT,                       -- Extracted hostname (e.g. "github.com")
    title TEXT,                        -- Window or tab title
    event_type TEXT NOT NULL,          -- "frontmost_application_changed", "tab_activated", "pomodoro_completed"
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_tracking_logs_local_date
    ON TrackingLogs (local_date, occurred_at DESC);
```

#### 2. `PomodoroTasks`
Manages user task queue items for Pomodoro tracking.

```sql
CREATE TABLE IF NOT EXISTS PomodoroTasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done')),
    estimate_pomodoros INTEGER NOT NULL DEFAULT 1,
    completed_pomodoros INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_completed_at TEXT
);
```

#### 3. `Tasks` (Compatibility View)
```sql
CREATE VIEW IF NOT EXISTS Tasks AS SELECT * FROM PomodoroTasks;
```

#### 4. `PersistentTimerState`
Singleton table (`id = 1`) persisting active Pomodoro timer state across application crashes or system restarts.

```sql
CREATE TABLE IF NOT EXISTS PersistentTimerState (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL DEFAULT 'idle',       -- 'idle', 'running', 'paused'
    phase TEXT NOT NULL DEFAULT 'work',         -- 'work', 'break'
    task_id INTEGER,
    remaining_seconds INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,                            -- ISO-8601 timestamp when running
    ends_at TEXT,                               -- ISO-8601 target end timestamp
    duration_at_start INTEGER NOT NULL DEFAULT 0,
    sessions_completed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
```

#### 5. `user_settings`
Singleton table (`id = 1`) storing user preferences and email outbox config.

```sql
CREATE TABLE IF NOT EXISTS user_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pomodoro_duration_minutes INTEGER NOT NULL DEFAULT 25,
    sleep_time TEXT NOT NULL DEFAULT '23:00',
    reflection_email TEXT,                     -- Target email address for outbox delivery
    updated_at TEXT NOT NULL
);
```

#### 6. `email_outbox`
Queues generated nightly reflection emails for asynchronous SMTP dispatch.

```sql
CREATE TABLE IF NOT EXISTS email_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_date TEXT NOT NULL,                 -- YYYY-MM-DD
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    is_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_email_outbox_sent ON email_outbox (is_sent, target_date);
```

---

## 5. API Endpoints Reference

### Core & Tracking

| Method | Endpoint | Description | Request Body / Query | Response |
+| --- | --- | --- | --- | --- |
+| `GET` | `/health` | Health check endpoint | None | `{"status": "ok"}` |
+| `POST` | `/track` | Receive activity webhook | `TrackingEvent` JSON | `{"id": int}` |

### Aggregations & Analytics

| Method | Endpoint | Description | Query Parameters | Response |
| --- | --- | --- | --- | --- |
| `GET` | `/active-time-summary` | Active app & domain breakdown for a date | `date` (YYYY-MM-DD, default today) | `{"totalSeconds": int, "apps": [...]}` |
| `GET` | `/activity/summary` | Multi-day laptop vs focus time summary | `days` (int, default 28) | `{"days": [{"date": "...", "total_laptop_time_seconds": int, ...}]}` |

### Pomodoro Timer Engine

| Method | Endpoint | Description | Request Body | Response |
| --- | --- | --- | --- | --- |
| `GET` | `/pomodoro` | Get current timer state snapshot | None | `TimerState` JSON |
| `POST` | `/pomodoro/start` | Start work session | `{"task_id": int?, "duration_seconds": int}` | Updated `TimerState` |
| `POST` | `/pomodoro/pause` | Pause running timer | None | Updated `TimerState` |
| `POST` | `/pomodoro/resume` | Resume paused timer | None | Updated `TimerState` |
| `POST` | `/pomodoro/stop` | Reset timer to idle | None | Updated `TimerState` |

### Task Management

| Method | Endpoint | Description | Request Body | Response |
| --- | --- | --- | --- | --- |
| `GET` | `/tasks` | List all tasks | None | `[Task, ...]` sorted by status & date |
| `GET` | `/tasks/{id}` | Retrieve specific task | None | `Task` JSON |
| `POST` | `/tasks` | Create new task | `{"title": str, "estimate_pomodoros": int}` | Created `Task` |
| `PATCH` | `/tasks/{id}` | Partial update task | `TaskUpdate` JSON | Updated `Task` |
| `DELETE` | `/tasks/{id}` | Delete task | None | `204 No Content` |

### Settings & Reflection Configuration

| Method | Endpoint | Description | Request Body | Response |
| --- | --- | --- | --- | --- |
| `GET` | `/settings` | Get current settings | None | `UserSettings` JSON |
| `PUT` | `/settings` | Update user settings | `SettingsUpdate` JSON | Updated `UserSettings` |

---

## 6. Key Design Patterns & Engineering Principles

### 1. SQL-Side Active Time Windowing (`LEAD() OVER ()`)
Active app durations are computed dynamically in SQLite using window functions without holding timer states in memory:
- Calculates duration between consecutive event timestamps (`LEAD(occurred_at) OVER (ORDER BY occurred_at)`).
- Caps event gaps at **15 minutes (900 seconds)** to ignore inactive periods.
- For today's ongoing session, compares the last event timestamp against `strftime('%s', 'now', 'localtime')`.

### 2. Thread-Safe Pomodoro State Machine
- Guarded by `asyncio.Lock()` in `backend/satan/timer.py`.
- On state transitions, state is persisted atomically to `PersistentTimerState`.
- On server lifespan startup (`load_persisted_timer_state`), elapsed wall-clock time is computed (`ends_at - now`) to automatically resume or auto-complete sessions expired while offline.
- When a work phase finishes, task `completed_pomodoros` is incremented, audio feedback (`"Work interval complete. Take a break."`) is triggered via macOS TTS, and an audit record (`event_type: 'pomodoro_completed'`) is inserted into `TrackingLogs`.

### 3. Outbox Pattern for Nightly Reflections
- **Generator Job**: Scheduled via APScheduler to fire daily at `Sleep Time - 15 minutes`.
  - **Critical Rule**: If total screen time for the date is `0`, generation is skipped.
  - Generates WatchOS-formatted subject: `Satan (Jul 24): 1h 40m Focus (15%) / 10h 58m Total`
  - Body first line: `🥇 Arc (8h 13m) | 🥈 Antigravity IDE (1h 4m) | 🥉 IntelliJ IDEA (39m)`
- **Queue Processor Job**: Runs every 5 minutes to deliver unsent outbox rows (`is_sent = 0`) via SMTP (`smtplib` with TLS).

### 4. Non-Blocking I/O in Desktop & Menu Bar Apps
- `mac_tracker.py` uses PyObjC `NSWorkspace` notifications. Webhook HTTP POST calls are offloaded to `ThreadPoolExecutor(max_workers=2)` so the Cocoa run loop (`AppHelper.runConsoleEventLoop`) never freezes.
- `menubar.py` uses `rumps`. HTTP calls to the backend are offloaded to `ThreadPoolExecutor` to keep the status bar responsive even when the API server is restarting.

### 5. Zero-Print Production Logging
- `satan.logger` defines structured rotating file handlers writing to `data/satan-server.log`, `data/satan-tracker.log`, and `data/satan-menubar.log`.
- No raw `print()` calls allowed in backend services or trackers.

---

## 7. Operational Runbook & Verification

### Local Development Setup

```zsh
cd Satan
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
npm --prefix dashboard install
```

### Running Services Manually

Start each service in a dedicated terminal window:

```zsh
# Backend API (Port 8200)
PYTHONPATH=backend ./.venv/bin/python backend/server.py

# macOS App Tracker
./.venv/bin/python trackers/mac_tracker.py

# Menu Bar App
./.venv/bin/python menu_bar/menubar.py

# React Dashboard (Port 3200)
npm --prefix dashboard run dev
```

### Running Automated Test Suite

Satan includes unit and integration tests covering API endpoints, task CRUD, tracker webhooks, SQL aggregations, timer state recovery, settings management, and reflection outbox generation.

```zsh
PYTHONPATH=backend ./.venv/bin/python -m pytest
```

### LaunchAgent Automation (Launch at Login)

```zsh
# Install LaunchAgent plists dynamically pointing to current working directory ($PWD)
./launchd/install_agents.sh

# Bootstrap with launchctl
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.server.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.tracker.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.menubar.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.dashboard.plist"
```

---

## 8. Agent Maintenance Rules

When operating on this codebase, AI coding agents MUST adhere to the following maintenance protocol:

1. **Keep `memory.md` Updated**: Any code edit, new API route, schema modification, or architectural change MUST be documented in `memory.md`.
2. **Preserve Test Suite 100% Pass Rate**: Run `PYTHONPATH=backend ./.venv/bin/python -m pytest` after making changes.
3. **Maintain Database Integrity**: Ensure all database queries use parameterized inputs and follow standard async `aiosqlite` context handling.
4. **Follow Zero-Print Constraint**: Use `logger.info()`, `logger.error()`, etc., from `satan.logger`. Do not introduce `print()` statements.
