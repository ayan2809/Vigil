# Vigil

Vigil is a local-first macOS activity tracker and Pomodoro service. Browser and foreground-app activity are delivered by operating-system/browser events only: there is no tracker polling loop. The API listens only on `127.0.0.1:8200`; the React dashboard runs locally on `127.0.0.1:3200` during development.

## Install and run

```zsh
cd /Users/ayan/Documents/Vigil
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
npm --prefix dashboard install
```

Start each local process in its own terminal:

```zsh
./.venv/bin/python backend/server.py
./.venv/bin/python trackers/mac_tracker.py
./.venv/bin/python menu_bar/menubar.py
npm --prefix dashboard run dev
```

Open [http://127.0.0.1:3200](http://127.0.0.1:3200). The server creates `data/vigil.db` and exposes interactive API documentation at [http://127.0.0.1:8200/docs](http://127.0.0.1:8200/docs).

## Browser extension

1. In Chrome, open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select `trackers/browser_extension`.
2. Browse or switch active tabs. Each activation, URL/title change, SPA history change, and focused-window change posts one webhook to Vigil.
3. The extension deliberately requests `<all_urls>` because a browser-wide tracker needs access to the active URL. It sends data only to `http://127.0.0.1:8200/track`.

The same WebExtension source can be converted for Safari on macOS using `xcrun safari-web-extension-converter trackers/browser_extension`; open the generated Xcode project, choose your signing team, and enable the extension in Safari. Safari requires this Xcode packaging/signing step.

## Validate the service

With the server running:

```zsh
curl http://127.0.0.1:8200/health
curl -X POST http://127.0.0.1:8200/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Verify Vigil","estimate_pomodoros":1}'
curl -X POST http://127.0.0.1:8200/track \
  -H 'Content-Type: application/json' \
  -d '{"source":"app","application_name":"Terminal","event_type":"frontmost_application_changed"}'
curl 'http://127.0.0.1:8200/history'
```

For a fast timer-transition check, launch the server with `VIGIL_WORK_SECONDS=5 VIGIL_BREAK_SECONDS=3` and start a Pomodoro. The server calls native macOS `say` at start, work completion, break completion, pause, resume, and stop.

## Launch at login

After the virtual environment is installed, copy the four LaunchAgents and bootstrap them for the current user:

```zsh
mkdir -p "$HOME/Library/LaunchAgents"
cp launchd/*.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.vigil.server.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.vigil.tracker.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.vigil.menubar.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.vigil.dashboard.plist"
```

To stop them later, use `launchctl bootout` with the corresponding `gui/$(id -u)` domain and plist path. Launchd writes diagnostics to log files in the `data/` directory (e.g., `data/vigil-server.log`, `data/vigil-tracker.log`, `data/vigil-menubar.log`, and `data/vigil-dashboard.log`).

## Design notes

- `TrackingLogs` stores browser/app events. `PomodoroTasks` stores task state; `Tasks` is a compatibility SQL view for the Phase 2 naming in the brief.
- The PyObjC tracker observes `NSWorkspace.frontmostApplication` through KVO, with the matching NSWorkspace activation notification as an event-only compatibility signal. It never loops to inspect the active app.
- The FastAPI timer schedules one `asyncio.sleep` per work or break phase, rather than continuously ticking. The dashboard and menu bar refresh only on user action or after a command.
