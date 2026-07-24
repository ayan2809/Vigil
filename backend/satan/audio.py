"""Native macOS speech synthesis module."""

from __future__ import annotations

import shlex
import subprocess
from satan.logger import logger


def speak(text: str) -> None:
    """Trigger macOS say synthesis asynchronously using non-blocking Popen."""
    try:
        subprocess.Popen(["say", text])
        logger.info(f"Speech announced: {text!r}")
    except Exception as exc:
        logger.error(f"Failed to execute say process: {exc}")


def announce(text: str) -> None:
    """Public speech trigger (fire-and-forget)."""
    speak(text)
