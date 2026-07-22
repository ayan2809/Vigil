"""Vigil FastAPI application factory and main entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from vigil.db import cleanup_old_logs, initialize_database
from vigil.logger import logger
from vigil.routes import pomodoro, settings, summary, tasks, tracking
from vigil.scheduler import shutdown_scheduler, start_scheduler
from vigil.timer import cancel_timer_job, load_persisted_timer_state, timer_completion_job


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Initializing Vigil backend server...")
    await initialize_database()
    await load_persisted_timer_state()
    await cleanup_old_logs(retention_days=30)
    await start_scheduler()
    yield
    logger.info("Shutting down Vigil backend server...")
    shutdown_scheduler()
    job = timer_completion_job
    cancel_timer_job()
    if job is not None:
        with suppress(Exception):
            await job


app = FastAPI(title="Vigil", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1):3200|chrome-extension://.*|safari-web-extension://.*)$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(tasks.router)
app.include_router(tracking.router)
app.include_router(summary.router)
app.include_router(pomodoro.router)
app.include_router(settings.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
