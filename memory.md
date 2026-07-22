# Vigil Project Memory

## Project Overview & Architecture

Vigil is a lightweight, local-first macOS background activity tracker and Pomodoro server designed around event delivery:

- **FastAPI Core (`backend/vigil/`)**: A modular Python FastAPI package that receives browser and application activity webhooks, manages task CRUD, and drives the Pomodoro state machine.
- **State Machine & Persistence (`timer.py`, `db.py`)**: Pomodoro state (`status`, `phase`, `remaining_seconds`, `started_at`, `ends_at`) is persisted to SQLite (`PersistentTimerState` table) on every transition. On server startup, state is automatically restored and wall-clock elapsed time calculated to resume or complete active sessions.
- **Async Database & SQL Aggregations (`db.py`, `routes/summary.py`)**: SQLite runs with WAL mode, `PRAGMA busy_timeout = 5000;`, and request-scoped dependency injection. Daily and 28-day activity aggregations use SQLite `LEAD(occurred_at) OVER (...)` window functions and `GROUP BY` to execute duration math directly in the database engine.
- **Automated Data Retention**: An automated 30-day retention cleanup (`cleanup_old_logs(30)`) purges tracking records older than 30 days during server startup, keeping the database bounded while maintaining the full 28-day heatmap grid.
- **Event-Driven App Tracker (`trackers/mac_tracker.py`)**: PyObjC observer monitors `NSWorkspace` active-application events via KVO and notifications. All callbacks include `try...except` exception safety and offload HTTP POST requests to a background `ThreadPoolExecutor`.
- **Event-Driven Browser Tracker (`trackers/browser_extension/`)**: Manifest V3 WebExtension sends active-tab URL and window events with an offline resilience queue (max 20 events in `chrome.storage.local`) that buffers logs when Vigil is unreachable and flushes upon reconnection.
- **Menu Bar Controls (`menu_bar/menubar.py`)**: Python `rumps` app providing timer controls and dashboard links with non-blocking background thread I/O for HTTP calls.
- **Audio Feedback (`audio.py`)**: Native macOS speech synthesis executed asynchronously via non-blocking `subprocess.Popen(["say", text])`.
- **Centralized Logging (`logger.py`)**: Rotating file loggers write structured logs to `data/vigil-server.log`, `data/vigil-tracker.log`, and `data/vigil-menubar.log`. Zero `print()` statements in production.
- **LaunchAgent Management (`launchd/install_agents.sh`)**: Script dynamically generates `.plist` files using `$PWD` and installs/bootstraps them via `launchctl`.

## Tech Stack & Active Ports

| Component | Technology | Port / Runtime |
| --- | --- | --- |
| API & Pomodoro Engine | Python 3.13, FastAPI, async SQLite | `8200` |
| Dashboard | React.js, Vite dev server | `3200` |
| Browser Tracker | Manifest V3 Extension (Chrome/Safari) | Sends webhooks to `http://127.0.0.1:8200/track` |
| macOS App Tracker | PyObjC, NSWorkspace events, ThreadPoolExecutor | Sends webhooks to `http://127.0.0.1:8200/track` |
| Menu Bar Controls | Python, rumps | Local process |
| Service Manager | macOS launchd | User LaunchAgents |

## Database Schema (Live and Deployed)

- `TrackingLogs`: event-sourced browser and active-application activity records. Fields: `id`, `occurred_at`, `local_date`, `source` (`browser` or `app`), `application_name`, `url`, `domain`, `title`, `event_type`, `metadata_json`. Indexed by `(local_date, occurred_at DESC)`.
- `PomodoroTasks`: task records. Fields: `id`, `title`, `status` (`todo`, `in_progress`, `done`), `estimate_pomodoros`, `completed_pomodoros`, `created_at`, `updated_at`, `last_completed_at`.
- `PersistentTimerState`: singleton persistence table (`id=1`). Fields: `status`, `phase`, `task_id`, `remaining_seconds`, `started_at`, `ends_at`, `duration_at_start`, `sessions_completed`, `updated_at`.
- `Tasks`: SQL compatibility view over `PomodoroTasks`.

## Current State

- Full architectural refactoring complete across Maintainability, Scalability, and Reliability pillars.
- Automated integration test suite in `tests/test_api.py` passing 100% (`pytest`).
- Verified zero `print()` statements across all Python modules.
- Active user LaunchAgents bootstrapped and running from workspace directory.
