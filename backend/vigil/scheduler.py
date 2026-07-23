"""APScheduler background jobs for nightly reflection outbox generation and queue processing."""

from __future__ import annotations

import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Any

from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from vigil.db import get_db, iso_now, local_now
from vigil.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

scheduler = AsyncIOScheduler()
NIGHTLY_JOB_ID = "generate_nightly_reflection"
PROCESSOR_JOB_ID = "process_email_outbox"


def parse_sleep_time_to_trigger(sleep_time_str: str) -> tuple[int, int]:
    """Calculate (hour, minute) for Trigger Time = Sleep Time - 15 minutes."""
    try:
        parts = sleep_time_str.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
    except Exception:
        hours, minutes = 23, 0

    total_minutes = (hours * 60 + minutes - 15) % 1440
    return total_minutes // 60, total_minutes % 60


def format_duration_short(seconds: int) -> str:
    """Format seconds into short watch-friendly string e.g. '4h 15m' or '30m'."""
    if seconds <= 0:
        return "0m"
    mins = seconds // 60
    hrs = mins // 60
    rem_mins = mins % 60
    if hrs > 0:
        if rem_mins > 0:
            return f"{hrs}h {rem_mins}m"
        return f"{hrs}h"
    return f"{rem_mins}m"


async def generate_nightly_reflection_payload(target_date: str | None = None) -> tuple[str, str, int] | None:
    """Generate WatchOS formatted subject & body for target_date. Returns (subject, body, total_laptop) or None."""
    today_str = target_date or local_now().date().isoformat()
    dt = datetime.fromisoformat(today_str)
    date_formatted = dt.strftime("%b %-d") if hasattr(dt, "strftime") else dt.strftime("%b %d")

    async for db in get_db():
        # Query total laptop time and app breakdown
        query_apps = """
        WITH EventWindow AS (
            SELECT
                source,
                COALESCE(application_name, CASE WHEN source = 'browser' THEN 'Arc' ELSE 'Unknown App' END) AS app_name,
                domain,
                occurred_at,
                LEAD(occurred_at) OVER (ORDER BY occurred_at ASC) AS next_occurred_at
            FROM TrackingLogs
            WHERE local_date = ? AND event_type != 'pomodoro_completed'
              AND COALESCE(application_name, '') NOT IN ('loginwindow', 'ScreenSaverEngine')
        ),
        EventDurations AS (
            SELECT
                source,
                app_name,
                domain,
                CASE
                    WHEN next_occurred_at IS NOT NULL THEN
                        MIN(MAX(0, CAST((strftime('%s', next_occurred_at) - strftime('%s', occurred_at)) AS INTEGER)), 900)
                    WHEN ? = ? THEN
                        MIN(MAX(0, CAST((strftime('%s', 'now', 'localtime') - strftime('%s', occurred_at)) AS INTEGER)), 900)
                    ELSE 60
                END AS duration
            FROM EventWindow
        )
        SELECT app_name, SUM(duration) AS total_duration
        FROM EventDurations
        WHERE duration > 0
        GROUP BY app_name
        ORDER BY total_duration DESC;
        """
        cursor = await db.execute(query_apps, (today_str, today_str, local_now().date().isoformat()))
        app_rows = await cursor.fetchall()
        await cursor.close()

        # Query total focus time
        query_focus = """
        SELECT SUM(COALESCE(CAST(json_extract(metadata_json, '$.duration_seconds') AS INTEGER), 1500)) AS total_focus
        FROM TrackingLogs
        WHERE local_date = ? AND event_type = 'pomodoro_completed';
        """
        cursor = await db.execute(query_focus, (today_str,))
        focus_row = await cursor.fetchone()
        await cursor.close()

    total_laptop = sum(r["total_duration"] for r in app_rows) if app_rows else 0
    total_focus = (focus_row["total_focus"] or 0) if focus_row else 0

    # CRITICAL LOGIC: If Total Laptop Time == 0 for the day, do NOT generate an email
    if total_laptop == 0:
        logger.info(f"Nightly reflection check for {today_str}: Total Laptop Time is 0. Aborting email generation.")
        return None

    focus_percent = round((total_focus / total_laptop) * 100) if total_laptop > 0 else 0

    # Subject Line: Vigil ([Date]): [Total Focus] ([Focus %]%) / [Total Laptop] Total
    subject = f"Vigil ({date_formatted}): {format_duration_short(total_focus)} Focus ({focus_percent}%) / {format_duration_short(total_laptop)} Total"

    # Body First Line: 🥇 [App1] ([Time]) | 🥈 [App2] ([Time]) | 🥉 [App3] ([Time])
    emojis = ["🥇", "🥈", "🥉"]
    top_apps_str_list = []
    for idx, row in enumerate(app_rows[:3]):
        app_name = row["app_name"]
        app_time = format_duration_short(row["total_duration"])
        emoji = emojis[idx] if idx < len(emojis) else "▫️"
        top_apps_str_list.append(f"{emoji} {app_name} ({app_time})")

    body_first_line = " | ".join(top_apps_str_list)

    # Full Body
    body_lines = [
        body_first_line,
        "",
        f"Date: {today_str}",
        f"Focus Time: {format_duration_short(total_focus)} ({focus_percent}%)",
        f"Laptop Time: {format_duration_short(total_laptop)}",
    ]
    body = "\n".join(body_lines)

    return subject, body, total_laptop


async def generate_nightly_reflection_job() -> None:
    """Outbox Generator Job: Runs nightly at (Sleep Time - 15m)."""
    today_str = local_now().date().isoformat()
    logger.info(f"Executing nightly reflection generator job for {today_str}...")

    async for db in get_db():
        # Check if already queued for today
        cursor = await db.execute("SELECT id FROM email_outbox WHERE target_date = ?", (today_str,))
        existing = await cursor.fetchone()
        await cursor.close()
        if existing:
            logger.info(f"Nightly reflection for {today_str} is already in outbox. Skipping.")
            return

    res = await generate_nightly_reflection_payload(today_str)
    if res is None:
        return

    subject, body, _ = res
    now_str = iso_now()

    async for db in get_db():
        await db.execute(
            """
            INSERT INTO email_outbox (target_date, subject, body, is_sent, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (today_str, subject, body, now_str),
        )
        await db.commit()
        logger.info(f"Queued nightly reflection email for {today_str} in email_outbox.")


async def process_email_outbox_job() -> None:
    """Queue Processor Job: Runs every 5 minutes to deliver unsent emails via smtplib."""
    async for db in get_db():
        cursor = await db.execute("SELECT reflection_email FROM user_settings WHERE id = 1")
        settings_row = await cursor.fetchone()
        await cursor.close()

        reflection_email = settings_row["reflection_email"] if settings_row else None
        if not reflection_email:
            # No target email configured
            return

        cursor = await db.execute("SELECT * FROM email_outbox WHERE is_sent = 0 ORDER BY id ASC")
        pending_rows = await cursor.fetchall()
        await cursor.close()

        if not pending_rows:
            return

        smtp_host = os.environ.get("SMTP_HOST", "").strip()
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "").strip()
        smtp_pass = os.environ.get("SMTP_PASSWORD", "").strip()
        smtp_from = os.environ.get("SMTP_FROM", smtp_user or "vigil@local")

        for row in pending_rows:
            outbox_id = row["id"]
            subject = row["subject"]
            body = row["body"]

            if not smtp_host:
                logger.warning("SMTP_HOST not configured in environment. Unsent email remains in outbox.")
                break

            try:
                msg = MIMEText(body, "plain", "utf-8")
                msg["Subject"] = subject
                msg["From"] = smtp_from
                msg["To"] = reflection_email

                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.starttls()
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.send_message(msg)

                now_str = iso_now()
                await db.execute(
                    "UPDATE email_outbox SET is_sent = 1, sent_at = ? WHERE id = ?",
                    (now_str, outbox_id),
                )
                await db.commit()
                logger.info(f"Successfully sent reflection email outbox ID {outbox_id} to {reflection_email}.")
            except Exception as exc:
                logger.error(f"Failed to send email outbox ID {outbox_id}: {exc}")
                break


def update_nightly_job_trigger(sleep_time_str: str) -> None:
    """Reschedule the nightly generator job when sleep_time changes."""
    hour, minute = parse_sleep_time_to_trigger(sleep_time_str)
    if scheduler.get_job(NIGHTLY_JOB_ID):
        scheduler.reschedule_job(NIGHTLY_JOB_ID, trigger="cron", hour=hour, minute=minute)
        logger.info(f"Rescheduled nightly reflection generator to fire daily at {hour:02d}:{minute:02d}.")


async def start_scheduler() -> None:
    """Initialize and start APScheduler jobs."""
    async for db in get_db():
        cursor = await db.execute("SELECT sleep_time FROM user_settings WHERE id = 1")
        row = await cursor.fetchone()
        await cursor.close()
        sleep_time_str = row["sleep_time"] if row else "23:00"

    hour, minute = parse_sleep_time_to_trigger(sleep_time_str)

    if not scheduler.get_job(NIGHTLY_JOB_ID):
        scheduler.add_job(
            generate_nightly_reflection_job,
            trigger="cron",
            hour=hour,
            minute=minute,
            id=NIGHTLY_JOB_ID,
            replace_existing=True,
        )

    if not scheduler.get_job(PROCESSOR_JOB_ID):
        scheduler.add_job(
            process_email_outbox_job,
            trigger="interval",
            minutes=5,
            id=PROCESSOR_JOB_ID,
            replace_existing=True,
        )

    if not scheduler.running:
        scheduler.start()
        logger.info(f"APScheduler started. Nightly reflection generator active at {hour:02d}:{minute:02d}, outbox processor interval: 5m.")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
