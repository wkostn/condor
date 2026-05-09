from __future__ import annotations

import logging
import os
from datetime import time, timezone

from telegram.ext import Application, ContextTypes

from config_manager import get_config_manager
from utils.config import ADMIN_USER_ID


log = logging.getLogger(__name__)

MORNING_REPORT_JOB = "phase1_morning_report"
STATUS_ALERTS_JOB = "phase1_status_alerts"
STATUS_STATE_KEY = "phase1_status_state"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_utc_time(hhmm: str, fallback_hour: int = 6, fallback_minute: int = 0) -> time:
    try:
        h, m = hhmm.split(":", 1)
        hour = max(0, min(23, int(h)))
        minute = max(0, min(59, int(m)))
        return time(hour=hour, minute=minute, tzinfo=timezone.utc)
    except Exception:
        return time(hour=fallback_hour, minute=fallback_minute, tzinfo=timezone.utc)


async def _collect_server_statuses() -> dict[str, bool]:
    cm = get_config_manager()
    statuses: dict[str, bool] = {}
    for server_name in cm.list_servers():
        try:
            data = await cm.check_server_status(server_name)
            statuses[server_name] = data.get("status") == "online"
        except Exception:
            statuses[server_name] = False
    return statuses


def _render_status_lines(statuses: dict[str, bool]) -> str:
    if not statuses:
        return "- No servers configured"
    lines = []
    for name in sorted(statuses):
        mark = "✅" if statuses[name] else "❌"
        state = "online" if statuses[name] else "offline"
        lines.append(f"- {mark} {name}: {state}")
    return "\n".join(lines)


async def _send_admin_message(application: Application, text: str) -> None:
    if not ADMIN_USER_ID:
        return
    try:
        await application.bot.send_message(chat_id=ADMIN_USER_ID, text=text)
    except Exception as e:
        log.warning("Failed to send Phase 1 monitoring message: %s", e)


async def morning_report_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    statuses = await _collect_server_statuses()
    online = sum(1 for v in statuses.values() if v)
    total = len(statuses)

    msg = (
        "🌅 Morning Report\n"
        f"Servers online: {online}/{total}\n\n"
        "Server status snapshot:\n"
        f"{_render_status_lines(statuses)}"
    )
    await _send_admin_message(context.application, msg)


async def status_alerts_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    current = await _collect_server_statuses()
    prev = context.application.bot_data.get(STATUS_STATE_KEY, {})

    transitions: list[str] = []
    for name, is_online in sorted(current.items()):
        if name not in prev:
            continue
        was_online = bool(prev[name])
        if was_online != is_online:
            state = "ONLINE" if is_online else "OFFLINE"
            icon = "✅" if is_online else "🚨"
            transitions.append(f"{icon} {name} is now {state}")

    context.application.bot_data[STATUS_STATE_KEY] = current

    if transitions:
        msg = "Server Status Alert\n\n" + "\n".join(transitions)
        await _send_admin_message(context.application, msg)


async def schedule_phase1_monitoring_jobs(application: Application) -> None:
    if not ADMIN_USER_ID:
        log.info("Phase 1 monitoring not scheduled: ADMIN_USER_ID not configured")
        return

    # Seed initial status state so first alert checks only transitions.
    application.bot_data[STATUS_STATE_KEY] = await _collect_server_statuses()

    if _env_bool("PHASE1_MORNING_REPORT_ENABLED", True):
        hhmm = os.getenv("PHASE1_MORNING_REPORT_UTC", "06:00")
        when = _parse_utc_time(hhmm)
        existing = application.job_queue.get_jobs_by_name(MORNING_REPORT_JOB)
        for job in existing:
            job.schedule_removal()
        application.job_queue.run_daily(
            morning_report_callback,
            time=when,
            name=MORNING_REPORT_JOB,
        )
        log.info("Scheduled Phase 1 morning report at %s UTC", hhmm)

    if _env_bool("PHASE1_STATUS_ALERTS_ENABLED", True):
        interval = _env_int("PHASE1_STATUS_ALERTS_INTERVAL_SEC", 300)
        existing = application.job_queue.get_jobs_by_name(STATUS_ALERTS_JOB)
        for job in existing:
            job.schedule_removal()
        application.job_queue.run_repeating(
            status_alerts_callback,
            interval=interval,
            first=30,
            name=STATUS_ALERTS_JOB,
        )
        log.info("Scheduled Phase 1 status alerts every %ss", interval)
