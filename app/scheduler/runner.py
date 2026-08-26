import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from app.config import get_settings
from app.scheduler.tasks import (
    get_ist_now,
    is_holiday_or_weekend,
    run_morning_checkin_reminders,
    run_evening_checkout_reminders,
    run_evening_approvals_digest,
)

logger = logging.getLogger("xeva.scheduler.runner")

IST = timezone(timedelta(hours=5, minutes=30))

class ReminderScheduler:
    """
    Automated Background Reminder Scheduler (IST Timezone).
    Dispatches:
      1. Morning Check-In Reminder (Mon-Fri, non-holiday)
      2. Evening Approvals Digest (Mon-Fri)
      3. Evening Check-Out Reminder (Mon-Fri, non-holiday)
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_runs: Dict[str, str] = {
            "checkin": "",
            "checkout": "",
            "approvals": ""
        }

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        settings = get_settings()
        if not settings.ENABLE_AUTOMATED_REMINDERS:
            logger.info("Automated reminders are disabled in settings (ENABLE_AUTOMATED_REMINDERS=False).")
            return

        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._loop(), name="xeva_reminder_scheduler")
        logger.info(
            f"🚀 Automated Reminder Scheduler started in IST:\n"
            f"  - Morning Check-In: {settings.CHECKIN_REMINDER_TIME_IST} IST\n"
            f"  - Evening Approvals: {settings.APPROVALS_DIGEST_TIME_IST} IST\n"
            f"  - Evening Check-Out: {settings.CHECKOUT_REMINDER_TIME_IST} IST"
        )

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("⏹️ Automated Reminder Scheduler stopped.")

    async def _loop(self):
        while self._running:
            try:
                await self._check_and_trigger()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in reminder scheduler loop: {e}", exc_info=True)

            # Sleep 30 seconds before next check
            await asyncio.sleep(30)

    async def _check_and_trigger(self):
        settings = get_settings()
        now = get_ist_now()
        current_time_str = now.strftime("%H:%M")
        today_date_str = now.strftime("%Y-%m-%d")

        # 1. Check Morning Check-In Reminder
        checkin_time = settings.CHECKIN_REMINDER_TIME_IST.strip()
        if current_time_str == checkin_time and self._last_runs.get("checkin") != today_date_str:
            self._last_runs["checkin"] = today_date_str
            logger.info(f"⏰ Triggering scheduled Morning Check-In Reminders at {current_time_str} IST...")
            asyncio.create_task(run_morning_checkin_reminders())

        # 2. Check Evening Approvals Digest
        approvals_time = settings.APPROVALS_DIGEST_TIME_IST.strip()
        if current_time_str == approvals_time and self._last_runs.get("approvals") != today_date_str:
            self._last_runs["approvals"] = today_date_str
            logger.info(f"📋 Triggering scheduled Evening Approvals Digest at {current_time_str} IST...")
            asyncio.create_task(run_evening_approvals_digest())

        # 3. Check Evening Check-Out Reminder
        checkout_time = settings.CHECKOUT_REMINDER_TIME_IST.strip()
        if current_time_str == checkout_time and self._last_runs.get("checkout") != today_date_str:
            self._last_runs["checkout"] = today_date_str
            logger.info(f"🌙 Triggering scheduled Evening Check-Out Reminders at {current_time_str} IST...")
            asyncio.create_task(run_evening_checkout_reminders())

    def get_status(self) -> Dict[str, Any]:
        settings = get_settings()
        now = get_ist_now()
        return {
            "running": self._running,
            "timezone": "Asia/Kolkata (IST)",
            "currentTimeIST": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "schedule": {
                "morningCheckIn": f"{settings.CHECKIN_REMINDER_TIME_IST} IST (Mon-Fri, non-holiday)",
                "eveningApprovals": f"{settings.APPROVALS_DIGEST_TIME_IST} IST (Mon-Fri)",
                "eveningCheckOut": f"{settings.CHECKOUT_REMINDER_TIME_IST} IST (Mon-Fri, non-holiday)",
            },
            "lastRuns": self._last_runs,
            "smtpConfigured": bool(settings.SMTP_ENABLED and settings.SMTP_USER and settings.SMTP_PASSWORD)
        }

# Global singleton instance
scheduler_instance = ReminderScheduler()
