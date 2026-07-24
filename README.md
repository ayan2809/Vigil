# Satan

Satan is a local-first macOS activity tracker and Pomodoro service. Browser and foreground-app activity are delivered by operating-system/browser events only: there is no tracker polling loop. The API listens on `127.0.0.1:8200`; the React dashboard runs locally on `127.0.0.1:3200` during development.

---

## Architecture Overview

Satan is structured as a modular system built for high maintainability, scalability, and reliability:

- **Backend (`backend/satan/`)**: Modularized FastAPI package featuring:
  - `db.py`: Async SQLite connection lifecycle with WAL mode, `PRAGMA busy_timeout = 5000;`, request-scoped dependencies, and an automated 30-day retention cleanup (`cleanup_old_logs`).
  - `timer.py`: Thread-safe Pomodoro state machine with persistence in SQLite (`PersistentTimerState` table) across restarts and automatic time calculation/resumption on lifespan startup.
  - `routes/`: Decoupled API routers (`tasks.py`, `tracking.py`, `summary.py`, `pomodoro.py`, `settings.py`).
  - `summary.py`: High-performance SQL aggregations using SQLite `LEAD(occurred_at) OVER (...)` window functions and `GROUP BY`.
  - `audio.py`: Asynchronous macOS speech synthesis using non-blocking `subprocess.Popen(["say", text])`.
  - `logger.py`: Centralized rotating file logger writing to `data/` (`satan-server.log`, `satan-tracker.log`, `satan-menubar.log`).
- **macOS App Tracker (`trackers/mac_tracker.py`)**: Uses PyObjC `NSWorkspace` KVO and activation notifications with `try...except` exception safety and background `ThreadPoolExecutor` HTTP delivery to ensure zero main-thread run loop blocking.
- **Menu Bar App (`menu_bar/menubar.py`)**: Lightweight status bar controls built on `rumps` with non-blocking background thread I/O for HTTP requests.
- **Browser Extension (`trackers/browser_extension/`)**: Manifest V3 extension with an offline resilience queue (max 20 events in `chrome.storage.local`) that buffers active-tab events when offline and flushes upon reconnection.
- **Dashboard (`dashboard/`)**: Vite + React single-page app displaying a 28-day activity signal, daily timeline, active time breakdown, task queue, and Pomodoro controls.

---

## Install & Run

```zsh
# Clone repository and enter project directory
cd Satan

# Create virtual environment and install dependencies
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# Install dashboard dependencies
npm --prefix dashboard install
```

Start each local process in its own terminal:

```zsh
PYTHONPATH=backend ./.venv/bin/python backend/server.py
./.venv/bin/python trackers/mac_tracker.py
./.venv/bin/python menu_bar/menubar.py
npm --prefix dashboard run dev
```

Open [http://127.0.0.1:3200](http://127.0.0.1:3200). The server creates `data/satan.db` and exposes interactive API documentation at [http://127.0.0.1:8200/docs](http://127.0.0.1:8200/docs).

---

## Browser Extension Setup

1. In Chrome/Arc, open `chrome://extensions` (or `arc://extensions`), enable **Developer mode**, choose **Load unpacked**, and select `trackers/browser_extension`.
2. Browse or switch active tabs. Each activation, URL/title change, SPA history change, and focused-window change posts one webhook to Satan.
3. The extension requests `<all_urls>` to track active URLs and sends data exclusively to `http://127.0.0.1:8200/track`.

For Safari on macOS, convert the extension using `xcrun safari-web-extension-converter trackers/browser_extension`, open the generated Xcode project, choose your signing team, and enable the extension in Safari preferences.

---

## Launch at Login (LaunchAgent Automation)

Generate dynamic LaunchAgent plists pointing to your active workspace directory (`$PWD`) and bootstrap them for the current macOS user:

```zsh
./launchd/install_agents.sh

# Bootstrap services with launchctl
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.server.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.tracker.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.menubar.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.dashboard.plist"
```

To stop them later:

```zsh
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.server.plist"
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.tracker.plist"
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.menubar.plist"
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.dashboard.plist"
```

Diagnostics and output are written to rotating logs in `data/`:
- `data/satan-server.log`
- `data/satan-tracker.log`
- `data/satan-menubar.log`
- `data/satan-dashboard.log`

---

## Testing

Run the automated integration and unit test suite with `pytest`:

```zsh
PYTHONPATH=backend ./.venv/bin/python -m pytest tests/
```

Tests cover task CRUD operations, webhook tracking, SQL duration aggregations, Pomodoro state transitions, settings management, reflection outbox generation, and SQLite state recovery across simulated server restarts.
