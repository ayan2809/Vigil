# Satan Agent Guidelines & Repository Rules

Welcome to **Satan**. This repository houses a local-first macOS background activity tracker, Pomodoro state engine, and daily reflection system. As an AI agent working on this codebase, you MUST adhere to the architectural rules, coding standards, and operational guidelines documented below.

---

## 1. Mandatory Repository Rules

### Rule 1: Always Keep `memory.md` Synchronized
- **`memory.md` is the living blueprint of this repository.**
- Whenever you add or update API endpoints, database schemas, environment variables, background jobs, background services, or architectural design patterns, **you MUST update `memory.md` immediately**.
- `memory.md` must remain 100% accurate regarding live schema, component structures, API routes, and active configuration.

### Rule 2: Zero `print()` Statements in Production Code
- Debug `print()` calls in production Python files (`backend/`, `trackers/`, `menu_bar/`) are strictly prohibited.
- Always use structured logging via `satan.logger` (or `setup_logger` in standalone scripts) which writes rotating logs to `data/satan-server.log`, `data/satan-tracker.log`, and `data/satan-menubar.log`.

### Rule 3: Non-Blocking Event Loops & Threading
- **Cocoa Event Loop (`trackers/mac_tracker.py`)**: The `AppHelper.runConsoleEventLoop` thread must remain completely non-blocking. Webhook HTTP POST calls must be dispatched off-thread using `ThreadPoolExecutor`.
- **Rumps UI Thread (`menu_bar/menubar.py`)**: Menu bar actions and auto-refresh timers must dispatch HTTP requests asynchronously using background worker threads so the macOS status bar UI never freezes.
- **FastAPI Event Loop (`backend/satan/`)**: Long-running or synchronous blocking operations must be offloaded to worker threads or handled asynchronously using `async`/`await`.

### Rule 4: Preserve the Zero-Polling Event-Driven Model
- Activity tracking in Satan is strictly **event-driven**.
- Do NOT introduce polling loops into trackers or backend processes to discover active applications or tabs. Trackers must react exclusively to OS notifications (`NSWorkspaceDidActivateApplicationNotification` / KVO) or browser tab events.

### Rule 5: Asynchronous Database Access & SQLite Concurrency
- All database access in the backend must use `aiosqlite` via the request-scoped dependency `get_db()`.
- Always maintain SQLite WAL mode (`PRAGMA journal_mode = WAL;`) and busy timeout (`PRAGMA busy_timeout = 5000;`).
- Always use parameterized queries (e.g. `execute("SELECT ... WHERE id = ?", (task_id,))`) to prevent SQL injection vulnerabilities.

### Rule 6: Mandatory Automated Test Validation
- After modifying backend code, routes, database logic, or models, you MUST execute the automated test suite:
  ```zsh
  PYTHONPATH=backend ./.venv/bin/python -m pytest
  ```
- All tests must pass cleanly (100% pass rate) before concluding any task.

### Rule 7: Preserving API Contracts & Backwards Compatibility
- Dashboard (`dashboard/`), Menu Bar (`menu_bar/`), and Trackers (`trackers/`) rely on strict JSON payload schemas.
- Do not alter existing API response key names or types (e.g. `/pomodoro`, `/tasks`, `/active-time-summary`) without updating all consuming clients in sync.

---

## 2. Component Guidelines & Code Patterns

### Backend (`backend/satan/`)
- **FastAPI Modular Structure**: Keep routes organized by domain inside `backend/satan/routes/` (`tasks.py`, `tracking.py`, `summary.py`, `pomodoro.py`, `settings.py`).
- **Database Helper (`db.py`)**: Use `local_now()` for offset-aware timestamps (`YYYY-MM-DDTHH:MM:SS+HH:MM`) when recording human-readable event times. Use `iso_now()` for standard ISO string generation.
- **Pomodoro Timer (`timer.py`)**: State transitions must acquire `timer_lock` (`async with timer_lock:`) and immediately call `save_timer_state(db)` to persist the state in `PersistentTimerState`.
- **Background Scheduler (`scheduler.py`)**: Outbox generation (`generate_nightly_reflection_job`) fires daily at `Sleep Time - 15m`. **Critical logic rule**: If total screen time (`total_laptop`) is 0, do NOT queue an email payload. The outbox processor (`process_email_outbox_job`) checks `is_sent = 0` every 5 minutes and sends via `smtplib`.

### macOS Application Tracker (`trackers/mac_tracker.py`)
- Uses PyObjC `NSWorkspace` KVO on `frontmostApplication` and `NSWorkspaceDidActivateApplicationNotification`.
- Filters out system lock/screensaver processes: `com.apple.loginwindow`, `com.apple.ScreenSaver.Engine`, `com.apple.lockscreen`.
- Wraps all ObjC callbacks in `try...except` blocks to prevent unhandled Cocoa exceptions from crashing the tracker.

### Browser Extension (`trackers/browser_extension/`)
- WebExtension Manifest V3 compatible with Arc, Google Chrome, Brave, and Safari.
- Implements an **offline resilience queue** in `chrome.storage.local` (max 20 items) to buffer events when Satan backend is offline, automatically flushing upon network reconnect.

### Menu Bar Application (`menu_bar/menubar.py`)
- Python status bar control built on `rumps`.
- Polls backend state every 5 seconds via non-blocking `_async_action`.
- Updates menu bar icon dynamically: `◔` (idle), `◷` (running), `◑` (paused), `!` (server unavailable).

### React Dashboard (`dashboard/`)
- Vite + React SPA listening on port `3200`.
- Displays 28-day activity signal grid, daily timeline, active time breakdown, task queue, and Pomodoro controls.

### LaunchAgent Automation (`launchd/`)
- Plist files in `launchd/` are installed via `./launchd/install_agents.sh`.
- Scripts generate dynamic absolute paths pointing to `$PWD` and install to `$HOME/Library/LaunchAgents/`.

---

## 3. Workflow Checklist for Agents

When implementing changes in this repository, complete the following steps:

1. **Understand & Inspect**: Review existing routes, models, and tests before writing code.
2. **Implement Code**: Write clean, modern Python 3.13 / React code following existing patterns.
3. **Run Automated Tests**:
   ```zsh
   PYTHONPATH=backend ./.venv/bin/python -m pytest
   ```
4. **Update `memory.md`**: Update schemas, endpoint documentation, architectural notes, or environment variables in `memory.md`.
5. **Verify**: Ensure zero unhandled exceptions and zero `print()` statements remain.
