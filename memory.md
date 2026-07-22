# Vigil Project Memory

## Project Overview & Architecture

Vigil is a lightweight macOS background activity tracker and Pomodoro server. It is designed around event delivery rather than periodic polling:

- A headless Python FastAPI server receives browser and application activity webhooks and owns Pomodoro state.
- A Manifest V3 browser extension reports active-tab URL changes to the local server with an offline resilience queue.
- A Python PyObjC tracker observes `NSWorkspace` active-application events with Key-Value Observing/notifications without foreground polling, running network calls asynchronously.
- SQLite is accessed asynchronously by the FastAPI service using WAL mode, busy timeout, and SQL window function aggregations.
- A local React dashboard presents activity history and Pomodoro tasks.
- A Python `rumps` menu-bar application provides fast controls using background thread I/O.
- Pomodoro audio cues use native macOS speech asynchronously via non-blocking `subprocess.Popen(["say", "text"])`.
- `launchd`, not cron, starts the server and app tracker.

## Tech Stack & Active Ports

| Component | Technology | Port / Runtime |
| --- | --- | --- |
| API and Pomodoro engine | Python, FastAPI, async SQLite | `8200` |
| Dashboard | React.js, served locally | `3200` |
| Browser tracker | Chrome/Safari extension, Manifest V3 | Sends webhooks to `http://127.0.0.1:8200/track` |
| macOS app tracker | Python, PyObjC, NSWorkspace events | Sends webhooks to `http://127.0.0.1:8200/track` |
| Menu bar controls | Python, rumps | Local process |
| Service manager | macOS launchd | User LaunchAgent |

## Database Schema (Live and Deployed)

- `TrackingLogs`: event-sourced browser and active-application activity records. Fields: ID, timestamp, local_date, source (`browser` or `app`), application_name, url, domain, event_type, metadata_json.
- `PomodoroTasks`: Pomodoro task records, including ID, title, status, estimated/completed session counts, timestamps, and last_completed_at.
- `PersistentTimerState`: Pomodoro timer state persistence table (ID=1 singleton) ensuring state recovery across server restarts.
- `Tasks`: SQL compatibility view over `PomodoroTasks`.

## Current State

- Architectural refactoring complete across all 5 phases addressing Maintainability, Scalability, and Reliability.
- Modularized backend package `vigil/` with `db.py`, `models.py`, `timer.py`, `audio.py`, `logger.py`, and `routes/`.
- Centralized rotating file logging configured for backend (`vigil-server.log`), app tracker (`vigil-tracker.log`), and menubar (`vigil-menubar.log`).
- Thread-safe timer snapshotting and persistent state recovery in SQLite across server crashes/restarts.
- SQL duration aggregation using `LEAD()` window functions and `GROUP BY` in SQLite.
- PyObjC exception safety and non-blocking background thread webhooks in `mac_tracker.py`.
- Non-blocking thread execution in `menubar.py` keeping the UI thread responsive.
- Offline resilience queue (max 20 events) in `background.js` browser extension.

## Next Steps

1. Run verification test suite (`pytest`) to validate unit and integration behavior.
2. Execute `launchd/install_agents.sh` to generate dynamic user LaunchAgents for auto-start.
