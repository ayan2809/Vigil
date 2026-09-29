# Development

> Practical commands for building, running, testing, and debugging this repo. This is the operational companion to [ARCHITECTURE.md](ARCHITECTURE.md).

## Prerequisites

- macOS (the tracker, menu bar, and TTS announcements are macOS-only; the backend and dashboard could theoretically run elsewhere but the system as a whole is designed for a single local Mac).
- Python 3.13 (per `memory.md`; `requirements.txt` pins compatible but not exact versions).
- Node.js + npm for the dashboard.

## Initial setup

```zsh
cd Satan   # or wherever this repo is checked out
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
npm --prefix dashboard install
cp .env.example .env   # then fill in real SMTP credentials
```

`requirements.txt` covers: `fastapi`, `uvicorn[standard]`, `aiosqlite`, `httpx`, `pyobjc-framework-Cocoa`, `rumps`, `apscheduler`. Note: `backend/satan/scheduler.py` also imports `dotenv` (`python-dotenv`) to load `.env` — this is **not currently listed in `requirements.txt`**, so a fresh `pip install -r requirements.txt` may leave `python-dotenv` missing unless it's already present globally or via another package's dependency. Verify with `./.venv/bin/pip show python-dotenv` before assuming a clean install works.

## Running locally

Each service is a separate long-running process; run each in its own terminal (or install as LaunchAgents — see below).

```zsh
# Backend API — http://127.0.0.1:8200 (Swagger UI at /docs)
PYTHONPATH=backend ./.venv/bin/python backend/server.py

# macOS foreground-app tracker
./.venv/bin/python trackers/mac_tracker.py

# Menu bar app
./.venv/bin/python menu_bar/menubar.py

# Dashboard dev server — http://127.0.0.1:3200
npm --prefix dashboard run dev
```

The backend creates `data/satan.db` on first run (WAL mode; `data/satan.db-shm` / `-wal` sidecar files are normal). If an older `data/vigil.db` exists and `data/satan.db` does not, `backend/satan/db.py` auto-copies it forward once (rename-compatibility shim — see [DECISIONS.md](DECISIONS.md)).

### Browser extension (manual load, not part of the Python/Node build)

1. `chrome://extensions` (or `arc://extensions`) → enable Developer mode → "Load unpacked" → select `trackers/browser_extension`.
2. It posts to `http://127.0.0.1:8200/track` by default; requests `<all_urls>` host permission to observe active tab URLs.
3. Safari: convert with `xcrun safari-web-extension-converter trackers/browser_extension`, then enable in Safari via the generated Xcode project.

## Building

- **Dashboard:** `npm --prefix dashboard run build` (Vite) produces `dashboard/dist/`. `npm --prefix dashboard run preview` serves that build on port 3200. Note: as of this writing, the LaunchAgent for the dashboard (`launchd/com.satan.dashboard.plist`) runs `npm run dev`, not `preview`/a static server — see the open question in ARCHITECTURE.md.
- **Backend/Python:** no build step; run directly from source.

## Testing

```zsh
PYTHONPATH=backend ./.venv/bin/python -m pytest
# or target a file:
PYTHONPATH=backend ./.venv/bin/python -m pytest tests/test_api.py -v
```

- `pytest.ini` sets `asyncio_mode = auto` (pytest-asyncio) — async test functions need no `@pytest.mark.asyncio` decorator to run, though the existing tests include it anyway (harmless, redundant under `auto` mode).
- Both test files point `SATAN_DB_PATH` at a dedicated file (`data/test_satan.db`, `data/test_satan_settings.db`) *before* importing `satan.db`, and delete it before/after each test via an autouse fixture — tests never touch the real `data/satan.db`.
- Tests exercise the FastAPI app in-process via `httpx.AsyncClient(transport=ASGITransport(app=app))` — no real network socket, no separate server process needed.
- **Rule from `.agents/AGENTS.md`:** the full suite must pass (100%) after any backend/route/model change, before considering the task done.
- There is no dashboard (JS) test suite — `dashboard/package.json` defines no `test` script.

## LaunchAgent installation (launch at login)

```zsh
./launchd/install_agents.sh          # generates plists for $PWD into ~/Library/LaunchAgents
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.server.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.tracker.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.menubar.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.dashboard.plist"
```

To stop: `launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.satan.<name>.plist"` for each. All four plists set `KeepAlive: true` and `RunAtLoad: true` with a 10-second `ThrottleInterval`, so a crashing process will be relaunched roughly every 10 seconds indefinitely — check the relevant log under `data/` if a service seems to be churning.

## Environment variables

Set via shell env or `.env` (loaded only by `backend/satan/scheduler.py` via `python-dotenv`, so **only scheduler/SMTP variables are guaranteed to be read from `.env`** — other modules read `os.environ` directly and rely on the process's actual environment, e.g. what a LaunchAgent's `<EnvironmentVariables>` block sets).

| Variable | Default | Read by |
|---|---|---|
| `SATAN_DB_PATH` | `data/satan.db` | `backend/satan/db.py` |
| `SATAN_DATA_DIR` | `data/` | `backend/satan/logger.py` |
| `SATAN_WORK_SECONDS` (falls back to `VIGIL_WORK_SECONDS`) | `1500` | `backend/satan/models.py` |
| `SATAN_BREAK_SECONDS` (falls back to `VIGIL_BREAK_SECONDS`) | `300` | `backend/satan/models.py` |
| `SATAN_TRACK_URL` (falls back to `VIGIL_TRACK_URL`) | `http://127.0.0.1:8200/track` | `trackers/mac_tracker.py` |
| `SATAN_API_URL` (falls back to `VIGIL_API_URL`) | `http://127.0.0.1:8200` | `menu_bar/menubar.py` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | empty / `587` / empty / empty / `SMTP_USER` or `satan@local` | `backend/satan/scheduler.py` (via `.env`) |

`.env.example` documents the SMTP block only — the `SATAN_*` overrides above are undocumented there and only discoverable by reading source. Consider adding them to `.env.example` if this becomes confusing in practice.

⚠️ **The working tree currently has a real Gmail address and app password checked into `.env`** (gitignored, so not committed) and duplicated in plaintext in two untracked scratch scripts at the repo root (`test_smtp.py`, `test_smtp_noauth.py`). These are not part of the application and are not tracked by git, but they exist on disk with a live credential — worth deleting or securing before sharing this working directory.

## Debugging workflow

- **Logs:** each long-running process writes rotating logs (5 MB × 3 backups) to `data/`:
  - `data/satan-server.log` — backend (also mirrors to stdout when run manually)
  - `data/satan-tracker.log` — macOS tracker
  - `data/satan-menubar.log` — menu bar app
  - `data/satan-dashboard.log` — only populated when run via LaunchAgent (npm's own output); no rotation since it's raw stdout redirection, not `satan.logger`.
- **API introspection:** `http://127.0.0.1:8200/docs` (Swagger UI) and `/health` for a liveness check.
- **Timer state inspection:** `GET /pomodoro` returns the live snapshot; the persisted fallback lives in the `PersistentTimerState` row (`id=1`) in `data/satan.db` if you need to inspect it directly via `sqlite3`.
- **Common failure: menu bar / tracker show "server unavailable."** Check `data/satan-server.log` first — both clients treat any `URLError` (connection refused/timeout) identically and just report the backend as down.
- **Common failure: nightly email never arrives.** Check, in order: (1) `user_settings.reflection_email` is set (`GET /settings`), (2) `SMTP_HOST` is actually loaded (only `scheduler.py` calls `load_dotenv`, so if you're running with a non-standard working directory the `.env` path resolution — `PROJECT_ROOT / ".env"` — might miss it), (3) `data/satan.db`'s `email_outbox` table for rows stuck at `is_sent = 0`, which indicates either a full SMTP outage or an auth failure logged in `satan-server.log`.
- **Resetting local state:** delete `data/satan.db*` (and stop all four processes first) to start from a clean database; it will be recreated with defaults on next backend startup.

## CI/CD

**There is no CI/CD configuration in this repository** (no `.github/workflows/`, no other CI config files found). Test execution and verification are manual, driven by the `.agents/AGENTS.md` rule to run `pytest` before considering any backend change complete.
