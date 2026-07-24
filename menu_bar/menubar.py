#!/usr/bin/env python3
"""Minimal menu-bar controls for Satan's local FastAPI server."""

from __future__ import annotations

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import rumps

# Add backend directory to sys.path for shared logger setup if available
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from satan.logger import setup_logger
    logger = setup_logger("satan.menubar", "satan-menubar.log")
except Exception:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("satan.menubar")

API_URL = os.environ.get("SATAN_API_URL", os.environ.get("VIGIL_API_URL", "http://127.0.0.1:8200"))
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="menubar_worker")


def format_remaining(seconds: int) -> str:
    minutes, seconds = divmod(max(seconds, 0), 60)
    return f"{minutes:02d}:{seconds:02d}"


def _make_http_request(method: str, path: str, payload: dict | None = None) -> dict:
    """Execute HTTP request synchronously (intended for execution on background threads)."""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{API_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8")
        logger.warning(f"HTTPError {error.code} on {method} {path}: {detail}")
        raise RuntimeError(detail) from error
    except URLError as error:
        logger.warning(f"URLError on {method} {path}: {error.reason}")
        raise RuntimeError("Satan server is not running") from error


class SatanMenuBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("◔", quit_button=None)
        self.status_item = rumps.MenuItem("Status: connecting…")
        self.pause_item = rumps.MenuItem("Pause / Resume", callback=self.pause_or_resume)
        self.menu = [
            self.status_item,
            rumps.MenuItem("Start 25-minute Pomodoro", callback=self.start),
            self.pause_item,
            rumps.MenuItem("Stop", callback=self.stop),
            None,
            rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
            rumps.MenuItem("Refresh status", callback=self.refresh),
            None,
            rumps.MenuItem("Quit Satan Menu Bar", callback=rumps.quit_application),
        ]

    def open_dashboard(self, _sender) -> None:
        import webbrowser
        webbrowser.open("http://127.0.0.1:3200")

    def show_error(self, error: Exception) -> None:
        logger.error(f"UI Error: {error}")
        rumps.alert("Satan", str(error))

    def render_status(self, timer: dict) -> None:
        state = timer.get("status", "idle")
        if state == "idle":
            self.status_item.title = "Status: idle"
            self.title = "◔"
        else:
            phase = timer.get("phase", "work").title()
            remaining = timer.get("remaining_seconds", 0)
            self.status_item.title = f"Status: {phase} {state} — {format_remaining(remaining)}"
            self.title = "◷" if state == "running" else "◑"

    def _async_action(self, method: str, path: str, payload: dict | None = None, show_dialog: bool = True) -> None:
        def task():
            try:
                result = _make_http_request(method, path, payload)
                self.render_status(result)
            except Exception as error:
                if show_dialog:
                    self.show_error(error)
                else:
                    self.status_item.title = "Status: server unavailable"
                    self.title = "!"

        executor.submit(task)

    @rumps.clicked("Start 25-minute Pomodoro")
    def start(self, _sender) -> None:
        self._async_action("POST", "/pomodoro/start", {"duration_seconds": 1500}, show_dialog=True)

    def pause_or_resume(self, _sender) -> None:
        def task():
            try:
                timer = _make_http_request("GET", "/pomodoro")
                path = "/pomodoro/pause" if timer.get("status") == "running" else "/pomodoro/resume"
                result = _make_http_request("POST", path)
                self.render_status(result)
            except Exception as error:
                self.show_error(error)

        executor.submit(task)

    @rumps.clicked("Stop")
    def stop(self, _sender) -> None:
        self._async_action("POST", "/pomodoro/stop", show_dialog=True)

    @rumps.clicked("Refresh status")
    def refresh(self, _sender=None) -> None:
        self._async_action("GET", "/pomodoro", show_dialog=(_sender is not None))

    @rumps.timer(5)
    def auto_refresh(self, _sender) -> None:
        self.refresh(_sender=None)


if __name__ == "__main__":
    logger.info("Starting Satan Menu Bar application...")
    app = SatanMenuBar()
    app.refresh()
    app.run()
