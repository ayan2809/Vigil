# Satan

**A local-first macOS activity tracker, Pomodoro timer, and focus-load coach.**

Satan (formerly "Vigil") exists to answer one question, honestly: *"What did I actually do today, versus what I intended to do?"*

It quietly records which apps and websites you use, runs a Pomodoro timer for deliberate focus sessions, and turns the gap between the two into feedback: how dense your focus was today, whether you are ramping your workload up, holding steady, or burning out, and a short reflection email each night before bed.

Everything runs on your own Mac, on `127.0.0.1`. There is no account, no cloud, no telemetry, and no multi-user mode. The only outbound network call is the optional nightly email over your own SMTP server.

---

## Features

### Automatic activity tracking
- **Foreground apps (macOS):** a PyObjC tracker records every app switch. It is event-driven from `NSWorkspace` notifications, with no polling loop.
- **Browser tabs (Chrome / Arc / Brave / Safari):** a Manifest V3 extension records tab activation, URL/title changes, SPA navigation, and window focus. It buffers up to 20 events offline and flushes them when the server is back.
- **Laptop time** is computed at read time from the gaps between events (each gap capped at 15 minutes), so idle time is never counted as active time.
- **Sleep, lid and display awareness:** closing the lid or letting the display go to power saving stops time from accruing and pauses your Pomodoro. See [Sleep brake](#sleep-brake).
- Lock screens and screensavers are ignored.

### Pomodoro timer and task queue
- Start, pause, resume, and stop work sessions (default 25 min work / 5 min break; configurable in Settings). Breaks start automatically after a work session.
- A **Focus queue** of tasks with session estimates, progress (`2/3 sessions`), and done/todo toggles. Start a session directly from a task.
- Voice announcements at phase changes (macOS `say`).
- **Crash- and restart-safe:** timer state is persisted, and a session that ended while the server was down is finished on startup.
- Focus time is credited from completed sessions. A session you pause and resume is still credited in full.

### Focus Load (progressive overload)
Inspired by Apple Fitness's *Training Load*. It compares your recent focus volume with what you are conditioned to:

| Term | Meaning |
| --- | --- |
| **Acute load** | Average daily load over the last **7 days** (including today, live). |
| **Chronic load (baseline)** | Average daily load over the last **28 days**. |
| **Daily load (FLU)** | `focus minutes × (0.5 + 0.5 × density)`, where **density** = focus time ÷ laptop time (0–1). Focused, dense days count for more. |
| **Variance** | `(acute − chronic) ÷ chronic`. |

The variance maps to one of five states: **Well below** (< −20%), **Below** (< −5%), **Steady** (up to +10%), **Above** (up to +30%), **Well above** (> +30%). A trend readout tells you whether load is rising, easing, or steady compared with a week ago.

The dashboard shows this as a summary card and an Apple-Health-style chart: daily load bars, 7-day and 28-day average lines, and a shaded "steady" band. Hover to see any day's load, variance, focus/laptop time, and density. A **30D / 60D / 90D** toggle changes the window. Cold start is handled honestly: "Day X of 7" before a week of data, and a "preliminary baseline" until 28 days exist.

### Dashboard
A single-page React app at `http://127.0.0.1:3200`:
- Live Pomodoro clock and today's laptop time
- Full-width Focus queue
- Monthly focus goal(s) banner
- 28-day activity heatmap (hover for focus/laptop time per day)
- Focus Load card and chart
- Daily rules (your personal core values)
- Time breakdown by app and, for browsers, by domain, for any date
- Settings: default Pomodoro length, sleep time, reflection email, monthly goals, daily rules

### Menu bar app
A `rumps` status-bar item that shows the timer state and lets you start, pause/resume, and stop a Pomodoro, open the dashboard, or refresh. It refreshes automatically on wake and shows "(screen off)" when the timer was auto-paused by sleep.

### Nightly reflection email
Fifteen minutes before your configured sleep time, Satan queues a short, Apple-Watch-friendly email: total focus time and focus %, total laptop time, and your top three apps. For example: `Satan (Sep 29): 2h 30m Focus (35%) / 7h 10m Total`.
- Uses an **outbox pattern**: generation and delivery are separate jobs, so a failed send is retried.
- **Sleep-resilient:** if the Mac was asleep at the trigger time it still runs on wake, and missed days from the past week are backfilled on startup.
- No email is generated on days with zero laptop time.

### Local and private by design
- Binds to `127.0.0.1` only. No auth is needed because nothing is exposed.
- Raw events are kept for 30 days. Finalized per-day totals are kept indefinitely so long-range history (Focus Load) survives that purge.
- Runs at login through `launchd` LaunchAgents, with rotating logs in `data/`.

---

## Sleep brake

Focus time and laptop time only mean something if they describe the same hours. When the lid closes, the system sleeps, or the display enters power saving, the tracker sends a single `system_sleep` event. Then:

- time after that moment is not counted as laptop time, until the next activity;
- a running Pomodoro (work or break) is **paused at the moment the lid closed**, even if the request only arrives after wake;
- the timer **does not auto-resume**. Coming back and finding it silently running again would over-credit focus, so resume is deliberate;
- on wake, the tracker immediately re-reports your frontmost app so tracking resumes without waiting for an app switch.

---

## How it works

Five independent processes talk only over HTTP and one shared SQLite file:

```
 macOS tracker ─┐
                ├─ POST /track ─▶  Backend (FastAPI, :8200) ◀─ polls /pomodoro ─ Menu bar
 Browser ext. ──┘                  │  SQLite: data/satan.db
                                   │  Pomodoro state machine · aggregation · scheduler
                                   ▼
                              Dashboard (React, :3200)
```

| Component | Path | Role |
| --- | --- | --- |
| Backend | `backend/satan/` | The only process that touches the database. Routes, Pomodoro state machine, active-time aggregation, Focus Load math, nightly email jobs. |
| macOS tracker | `trackers/mac_tracker.py` | Reports foreground-app changes and sleep/wake, from OS notifications only. |
| Browser extension | `trackers/browser_extension/` | Reports active-tab changes, with an offline queue. |
| Menu bar app | `menu_bar/menubar.py` | Timer glance and controls. |
| Dashboard | `dashboard/` | Single-file React UI (`src/App.jsx`). |

Activity is **event-sourced**: raw timestamped events go into `TrackingLogs`, and durations are derived at read time with SQL window functions (`backend/satan/activity.py`, the single home of that logic).

---

## Install & Run

**Requirements:** macOS, Python 3.13, Node.js (for the dashboard).

```zsh
# From the project directory
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
npm --prefix dashboard install
```

Start each process in its own terminal:

```zsh
PYTHONPATH=backend ./.venv/bin/python backend/server.py   # API on :8200 (docs at /docs)
./.venv/bin/python trackers/mac_tracker.py                # app tracker
./.venv/bin/python menu_bar/menubar.py                    # menu bar app
npm --prefix dashboard run dev                            # dashboard on :3200
```

Open [http://127.0.0.1:3200](http://127.0.0.1:3200). The server creates `data/satan.db` on first run, and interactive API docs are at [http://127.0.0.1:8200/docs](http://127.0.0.1:8200/docs).

> The backend must run as a **single Uvicorn worker**: Pomodoro state is held in process memory.

### Nightly email (optional)

Copy `.env.example` to `.env` and fill in your SMTP settings (for Gmail, use an [App Password](https://support.google.com/accounts/answer/185833)). Then set your reflection email and sleep time in the dashboard's Settings.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SMTP_HOST` / `SMTP_PORT` | none / `587` | SMTP server |
| `SMTP_USER` / `SMTP_PASSWORD` | none | SMTP credentials |
| `SMTP_FROM` | `SMTP_USER` | From address |
| `SATAN_DB_PATH` | `data/satan.db` | Database location |
| `SATAN_WORK_SECONDS` / `SATAN_BREAK_SECONDS` | `1500` / `300` | Fallback Pomodoro lengths |
| `SATAN_TRACK_URL` | `http://127.0.0.1:8200/track` | Where trackers send events |

`.env` is gitignored. Keep credentials out of the repository.

### Browser extension

1. Open `chrome://extensions` (or `arc://extensions`), enable **Developer mode**, choose **Load unpacked**, and select `trackers/browser_extension`.
2. Browse normally. The extension sends data only to `http://127.0.0.1:8200/track`.

For Safari: `xcrun safari-web-extension-converter trackers/browser_extension`, open the generated Xcode project, pick a signing team, and enable the extension in Safari settings.

### Launch at login

```zsh
./launchd/install_agents.sh      # writes the plists for the current directory

launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.server.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.tracker.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.menubar.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.dashboard.plist"
```

Replace `bootstrap` with `bootout` to stop them, or restart one with `launchctl kickstart -k "gui/$(id -u)/com.satan.server"`. After changing backend code, restart the server the same way. Logs are in `data/` (`satan-server.log`, `satan-tracker.log`, `satan-menubar.log`, `satan-dashboard.log`).

---

## API at a glance

Interactive docs live at `/docs`. Main endpoints:

| Endpoint | Purpose |
| --- | --- |
| `POST /track` | Ingest an activity event (used by the trackers). |
| `GET /active-time-summary?date=` | App and domain breakdown for a day. |
| `GET /activity/summary?days=` | Per-day laptop vs focus time (the heatmap). |
| `GET /focus-load?days=30\|60\|90` | Acute/chronic load, classification, trend, and chart series. |
| `GET /pomodoro`, `POST /pomodoro/{start,pause,resume,stop}` | Timer state and controls. |
| `GET/POST/PATCH/DELETE /tasks` | Focus queue. |
| `GET/PUT /settings` | Pomodoro length, sleep time, reflection email, goals, daily rules. |

---

## Testing

```zsh
PYTHONPATH=backend ./.venv/bin/python -m pytest
```

Covers task CRUD, tracking and aggregation, Pomodoro transitions and restart recovery, the sleep brake, Focus Load math (classification boundaries, cold start, rolling history, trend), the daily rollup, settings, and the email outbox. `pytest.ini` limits collection to `tests/`.

---

## Project docs

- [`memory.md`](memory.md): fast-reference schema, API, and env blueprint (kept in sync on every change)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): components, runtime diagram, constraints
- [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md): ingest, aggregation, Pomodoro, and email lifecycles
- [`docs/CODEBASE_GUIDE.md`](docs/CODEBASE_GUIDE.md): repo layout and "where do I change X?"
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md): build, run, test, debug
- [`docs/DECISIONS.md`](docs/DECISIONS.md): why things are shaped this way
- [`docs/GLOSSARY.md`](docs/GLOSSARY.md): domain terms
- [`docs/proposals/focus-load-plan.md`](docs/proposals/focus-load-plan.md): Focus Load design

## Design principles

1. **No polling for activity.** Trackers react to OS and browser events only.
2. **No blocking I/O on event-loop or UI threads.** Tracker and menu bar HTTP calls run on worker threads.
3. **One database owner.** Only the backend touches SQLite (WAL mode, parameterized queries).
4. **Local only.** Loopback binding, no cloud dependencies beyond your own SMTP server.
