# Decisions

> Architectural/design decisions inferred from the code and git history. Facts are cited to a specific file or commit; rationale beyond that is explicitly marked as inference.

## 1. Project rename: Vigil → Satan

**Fact:** Commit `d3447d8` ("Rename project to Satan across backend, trackers, menubar, dashboard, emails, launchd plists, and tests") renamed the product from "Vigil" to "Satan" throughout most of the codebase. This is the single most recent structural change before the current work.

**Evidence the rename is incomplete / still transitioning:**
- The on-disk directory and git remote context are still `Vigil` (working directory path `/Volumes/Projects/Vigil`).
- `dashboard/package.json` still has `"name": "vigil-dashboard"`.
- `backend/satan/db.py` contains an explicit one-time migration: if `data/satan.db` doesn't exist but `data/vigil.db` does, it copies the old DB forward.
- Environment variables are read with `SATAN_*` first, `VIGIL_*` as fallback, in `backend/satan/models.py`, `trackers/mac_tracker.py`, and `menu_bar/menubar.py`.
- The browser extension's `chrome.storage.local` lookup checks both `satanServerUrl` and the legacy `vigilServerUrl` key (`background.js`).
- Log/data file names on disk currently include both `satan-*` and `vigil-*` variants (`data/` directory listing), consistent with a mid-rename state where old LaunchAgents/processes may not yet have been fully replaced.

**Inference:** this is a deliberate, careful backward-compatibility strategy for a rename — the author is avoiding a "flag day" cutover that would orphan old data or break already-installed LaunchAgents/extension configs. Not confirmed by any comment or commit message explaining *why* the rename happened at all (no evidence found either way).

## 2. Event-sourced activity log instead of a running-duration state table

**Fact:** `TrackingLogs` stores discrete point-in-time events, never a start/end interval or accumulated duration. All duration figures are computed at read time via SQL window functions (see [DATA_FLOW.md](DATA_FLOW.md#2-active-time-computation-read-path)).

**Inference:** this avoids needing to track "session start" state across tracker restarts, browser reloads, or system sleep — a single event stream is trivially append-only and crash-safe, whereas a stateful "current session" model would need its own recovery logic (as the Pomodoro timer does, at real cost — see PersistentTimerState below). The tradeoff was that the same aggregation SQL had to be written three times (summary endpoint, heatmap endpoint, nightly email) rather than being computed once and stored. **Update:** that duplication was removed by the Focus Load work (see decision 8) — the SQL now lives once in `backend/satan/activity.py`.

## 3. Explicit 15-minute (900s) cap on inferred activity gaps

**Fact:** every duration computation caps the gap between two consecutive events at 900 seconds (`MIN(..., 900)`), consistently at the single aggregation site (`backend/satan/activity.py`).

**Inference:** without this cap, leaving a laptop open and idle (or asleep with the tracker still "seeing" a stale last event) would be counted as continuous active time until the next event arrives — potentially hours. 900s was chosen as a threshold beyond which a gap is assumed to represent inactivity rather than continuous engagement with the same app/tab. The specific value (15 min, not 5 or 30) is not explained anywhere in code or commits — treat it as a tuned-by-feel constant, not a derived one.

## 4. Outbox pattern for email delivery, decoupled from generation

**Fact:** `email_outbox` table + two separate scheduled jobs (`generate_nightly_reflection_job` writes, `process_email_outbox_job` sends), both configured with `misfire_grace_time=3600` and `coalesce=True` (commit `434af18`, "Fix missed email reflections with misfire_grace_time and startup backfill catch-up").

**Inference (well-supported by the commit history and code comments):** this exists specifically to handle a MacBook sleeping through the exact scheduled trigger minute. APScheduler's default behavior would treat a job as "missed" if the process wasn't running at the exact fire time; `misfire_grace_time=3600` tells it to run anyway if it wakes within an hour of the scheduled time, and `check_and_backfill_missing_reflections` (also added in the same commit) is a belt-and-suspenders catch-up for the case where even that grace window was missed (e.g. laptop closed overnight). This is a clear "fix a real bug encountered in production use" commit, not a speculative feature — the commit message itself confirms the motivating failure mode.

## 5. Nightly email skipped entirely when laptop time is 0

**Fact:** `generate_nightly_reflection_payload` returns `None` (no outbox row written) if `total_laptop == 0` for the target date, enforced by a dedicated test (`test_outbox_generator_critical_zero_laptop_time_rule`) and called out as a "CRITICAL RULE" in both `memory.md` and inline comments.

**Inference:** this prevents a meaningless/embarrassing "0h 0m Focus / 0h 0m Total" email from being sent on days the Mac was never used (e.g. travel, days off). The rule is explicitly tested and documented, suggesting it was a deliberate product decision rather than an incidental side effect.

## 6. Dual monthly-goal fields (`monthly_goal` singular + `monthly_goals` array)

**Fact:** commit `eb887a6` ("Support multiple monthly focus goals...") added `monthly_goals` (JSON array) alongside the pre-existing `monthly_goal` (singular string) column, with `monthly_goal` derived as `monthly_goals[0]` on every write (`backend/satan/routes/settings.py::update_settings`).

**Inference:** this is a backward-compatible schema evolution — any older client or code path still reading `monthly_goal` keeps working, while new functionality (multiple goals, rendered as a bulleted list by `MonthlyGoalBanner` in `App.jsx` when there's more than one) is additive. Same pattern as the Vigil→Satan env var fallback: prefer additive, dual-read migrations over breaking changes, consistent across this codebase.

## 7. In-memory Pomodoro state as the source of truth, SQLite as recovery-only

**Fact:** `timer_state` is a single module-level dataclass instance (`backend/satan/timer.py`), not re-read from the database on every request; `PersistentTimerState` is written on every mutation but only *read* once, at server startup (`load_persisted_timer_state`).

**Inference:** this is a deliberate performance/simplicity choice for a single-process, single-user backend — there's no need to pay a DB round-trip for every `GET /pomodoro` poll (called every 5s by the menu bar) when the state fits trivially in memory and there's exactly one server process. This would not scale to multiple backend workers/processes without a redesign (e.g. Uvicorn with `workers > 1` would create independent, inconsistent `timer_state` instances) — worth flagging if anyone ever considers running this with more than one worker process. `backend/server.py` currently hardcodes `uvicorn.run(..., reload=False)` with no `workers` argument, i.e. single worker, consistent with this design.

## Open questions / uncertain areas

- No commit message or comment explains *why* the product was renamed from Vigil to Satan, or whether more rename cleanup (directory rename, full `VIGIL_*` fallback removal, `vigil-dashboard` package name) is planned or intentionally left as-is.
- No evidence of a deliberate decision *not* to add a production static-file server for the dashboard build — could be an oversight or could be intentional given the single-user, dev-server-is-fine context. Flagged, not resolved, in [ARCHITECTURE.md](ARCHITECTURE.md).
- The 900-second activity-gap cap and the 60-second flat fallback for trailing events on past days (see [DATA_FLOW.md](DATA_FLOW.md)) are unexplained tuned constants — no A/B data or rationale found in commits or comments.

## 8. Focus Load feature: shared aggregation, daily rollup, and sleep brake

**Fact (branch `feature/progressive-overload`, design in [proposals/focus-load-plan.md](proposals/focus-load-plan.md)):**
- **Focus Load** compares 7-day (acute, includes today) to 28-day (chronic) focus volume, Apple Training Load style. Computed in Python (`focus_load.py`, pure), served by `GET /focus-load`; the frontend only renders.
- **Shared SQL.** The active-time SQL was extracted to `activity.py` and the three former copies now call it. Verified output-identical against the real database before merging.
- **`DailyActivityRollup` table.** Raw `TrackingLogs` are purged after 30 days on every startup, which is too short for a 30/60/90-day chart with a rolling 28-day baseline. Finalized days are therefore persisted (rollup runs *before* the purge; if it fails, the purge is skipped that startup). Today is always live. Rolled-up days are frozen: later changes to the duration logic don't rewrite them.
- **Sleep brake.** The tracker emits `system_sleep` on lid close / display sleep. Aggregation treats it as a terminator (the span after it is never counted) and the backend auto-pauses the Pomodoro at the sleep moment. Chosen so focus and laptop time stay comparable (focus previously kept accruing while the machine slept).
- **No auto-resume on wake** (deliberate): silently restarting a timer after, say, lunch would recreate the over-credit problem.
- **`session_duration`** was added because resuming a paused Pomodoro previously credited only the remaining time.

**Known limits:** history recorded before the sleep brake can over-count laptop time by up to 15 min per sleep (only historical *density* is affected; focus minutes are unaffected). `pytest.ini` now sets `testpaths = tests` and a root `conftest.py` ignores the untracked `test_smtp*.py` scripts, which connect to SMTP at import time.

