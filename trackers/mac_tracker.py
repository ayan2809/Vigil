#!/usr/bin/env python3
"""Event-driven foreground application tracker for macOS.

NSWorkspace KVO and its activation notification both arrive from macOS only
when the foreground application changes. AppHelper runs Cocoa's event loop;
there is no foreground-app polling loop in this process.

Sleep/wake and display sleep/wake notifications are likewise pushed by macOS. Entering
"away" (lid closed, system asleep, or display in power saving) emits a single
`system_sleep` event so the backend stops counting time and pauses the Pomodoro;
leaving "away" re-emits the frontmost app so tracking resumes immediately.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from AppKit import (
    NSWorkspace,
    NSWorkspaceDidActivateApplicationNotification,
    NSWorkspaceDidWakeNotification,
    NSWorkspaceScreensDidSleepNotification,
    NSWorkspaceScreensDidWakeNotification,
    NSWorkspaceWillSleepNotification,
)
from Foundation import NSKeyValueChangeNewKey, NSKeyValueObservingOptionNew, NSObject
from PyObjCTools import AppHelper
from objc import super as objc_super

# Add backend directory to sys.path for shared logging setup if available
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from satan.logger import setup_logger
    logger = setup_logger("satan.tracker", "satan-tracker.log")
except Exception:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("satan.tracker")

SERVER_URL = os.environ.get("SATAN_TRACK_URL", os.environ.get("VIGIL_TRACK_URL", "http://127.0.0.1:8200/track"))
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mac_tracker_worker")


def _send_webhook(server_url: str, payload: dict) -> None:
    """Perform HTTP POST on a background worker thread."""
    request = Request(
        server_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=2):
            logger.debug(f"Event delivered: {payload.get('event_type')} {payload.get('application_name')!r}")
    except URLError as error:
        logger.warning(f"Vigil tracker webhook unavailable: {error.reason}")
    except Exception as exc:
        logger.error(f"Unexpected error posting tracker event: {exc}")


IGNORED_BUNDLE_IDS = {
    "com.apple.loginwindow",
    "com.apple.ScreenSaver.Engine",
    "com.apple.lockscreen",
}

IGNORED_APP_NAMES = {
    "loginwindow",
    "ScreenSaverEngine",
}


class WorkspaceObserver(NSObject):
    def initWithServerURL_(self, server_url: str):  # noqa: N802 - required Objective-C selector spelling
        self = objc_super(WorkspaceObserver, self).init()
        if self is None:
            return None
        self.server_url = server_url
        self.workspace = NSWorkspace.sharedWorkspace()
        self.last_process_id: int | None = None
        self.system_asleep = False
        self.screens_asleep = False
        self.away = False
        return self

    def start(self) -> None:
        try:
            # Primary path: KVO reports changes to NSWorkspace.frontmostApplication.
            self.workspace.addObserver_forKeyPath_options_context_(
                self, "frontmostApplication", NSKeyValueObservingOptionNew, None
            )
            # NSWorkspace's activation notification covers macOS versions where a
            # KVO change is coalesced. Deduplication below prevents double writes.
            self.workspace.notificationCenter().addObserver_selector_name_object_(
                self,
                "workspaceDidActivateApplication:",
                NSWorkspaceDidActivateApplicationNotification,
                None,
            )
            center = self.workspace.notificationCenter()
            for selector, name in (
                ("systemWillSleep:", NSWorkspaceWillSleepNotification),
                ("systemDidWake:", NSWorkspaceDidWakeNotification),
                ("screensDidSleep:", NSWorkspaceScreensDidSleepNotification),
                ("screensDidWake:", NSWorkspaceScreensDidWakeNotification),
            ):
                center.addObserver_selector_name_object_(self, selector, name, None)
            self.emit_application(self.workspace.frontmostApplication())
            logger.info("WorkspaceObserver started successfully.")
        except Exception as exc:
            logger.error(f"Error starting WorkspaceObserver: {exc}")

    def stop(self) -> None:
        try:
            self.workspace.removeObserver_forKeyPath_(self, "frontmostApplication")
            self.workspace.notificationCenter().removeObserver_(self)
            logger.info("WorkspaceObserver stopped.")
        except Exception as exc:
            logger.error(f"Error stopping WorkspaceObserver: {exc}")

    def observeValueForKeyPath_ofObject_change_context_(self, key_path, _object, change, _context):
        try:
            if key_path == "frontmostApplication":
                application = change.objectForKey_(NSKeyValueChangeNewKey)
                self.emit_application(application or self.workspace.frontmostApplication())
        except Exception as exc:
            logger.error(f"Error in observeValueForKeyPath: {exc}")

    def workspaceDidActivateApplication_(self, notification):  # noqa: N802 - Objective-C selector
        try:
            application = notification.userInfo().objectForKey_("NSWorkspaceApplicationKey")
            self.emit_application(application)
        except Exception as exc:
            logger.error(f"Error in workspaceDidActivateApplication: {exc}")

    def systemWillSleep_(self, _notification):  # noqa: N802 - Objective-C selector
        self.system_asleep = True
        self._update_away()

    def systemDidWake_(self, _notification):  # noqa: N802 - Objective-C selector
        self.system_asleep = False
        self._update_away()

    def screensDidSleep_(self, _notification):  # noqa: N802 - Objective-C selector
        self.screens_asleep = True
        self._update_away()

    def screensDidWake_(self, _notification):  # noqa: N802 - Objective-C selector
        self.screens_asleep = False
        self._update_away()

    def _update_away(self) -> None:
        """Emit only on transitions of "away" so a lid close (system + screens) is one event."""
        try:
            away = self.system_asleep or self.screens_asleep
            if away == self.away:
                return
            self.away = away
            if away:
                payload = {
                    "source": "app",
                    "event_type": "system_sleep",
                    "metadata": {"reason": "system" if self.system_asleep else "display"},
                    # The request may only complete after wake; the backend needs the real time.
                    "occurred_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
                executor.submit(_send_webhook, self.server_url, payload)
                logger.info(f"Away: {payload['metadata']['reason']} sleep.")
            else:
                # Foreground app is unchanged across sleep, so the dedup below would swallow it.
                self.last_process_id = None
                self.emit_application(self.workspace.frontmostApplication())
                logger.info("Back from sleep; resumed tracking.")
        except Exception as exc:
            logger.error(f"Error handling sleep/wake transition: {exc}")

    def emit_application(self, application) -> None:
        try:
            if application is None:
                return
            bundle_id = str(application.bundleIdentifier() or "")
            app_name = str(application.localizedName() or "Unknown")

            if bundle_id in IGNORED_BUNDLE_IDS or app_name in IGNORED_APP_NAMES:
                logger.debug(f"Ignoring system lock process {app_name!r} ({bundle_id})")
                return

            process_id = int(application.processIdentifier())
            if process_id == self.last_process_id:
                return
            self.last_process_id = process_id
            payload = {
                "source": "app",
                "application_name": app_name,
                "event_type": "frontmost_application_changed",
                "metadata": {
                    "bundle_id": bundle_id,
                    "process_id": process_id,
                },
            }
            # Dispatch HTTP request off the main Cocoa run loop
            executor.submit(_send_webhook, self.server_url, payload)
        except Exception as exc:
            logger.error(f"Error in emit_application: {exc}")


def main() -> None:
    observer = WorkspaceObserver.alloc().initWithServerURL_(SERVER_URL)
    observer.start()
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except Exception as exc:
        logger.error(f"Unhandled exception in Cocoa event loop: {exc}")
    finally:
        observer.stop()
        executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
