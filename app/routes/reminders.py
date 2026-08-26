from fastapi import APIRouter, Query
from typing import Dict, Any

from app.scheduler.runner import scheduler_instance
from app.scheduler.tasks import (
    run_morning_checkin_reminders,
    run_evening_checkout_reminders,
    run_evening_approvals_digest,
    is_holiday_or_weekend,
    get_ist_now,
)

router = APIRouter(prefix="/reminders", tags=["Reminders & Notifications"])

@router.get("/status")
async def get_reminder_status() -> Dict[str, Any]:
    """Get the current status of the automated reminder scheduler."""
    status = scheduler_instance.get_status()
    is_skip, reason = await is_holiday_or_weekend()
    status["todayContext"] = {
        "isHolidayOrWeekend": is_skip,
        "classification": reason
    }
    return status

@router.post("/trigger-checkin")
async def trigger_checkin_reminders(force: bool = Query(default=False, description="Bypass weekend/holiday check for testing")) -> Dict[str, Any]:
    """Manually trigger the morning check-in reminder job."""
    result = await run_morning_checkin_reminders(force=force)
    return {
        "job": "morning_checkin_reminders",
        "result": result
    }

@router.post("/trigger-checkout")
async def trigger_checkout_reminders(force: bool = Query(default=False, description="Bypass weekend/holiday check for testing")) -> Dict[str, Any]:
    """Manually trigger the evening check-out reminder job."""
    result = await run_evening_checkout_reminders(force=force)
    return {
        "job": "evening_checkout_reminders",
        "result": result
    }

@router.post("/trigger-approvals")
async def trigger_approvals_digest(force: bool = Query(default=False, description="Force trigger digest")) -> Dict[str, Any]:
    """Manually trigger the evening manager approvals digest job."""
    result = await run_evening_approvals_digest(force=force)
    return {
        "job": "evening_approvals_digest",
        "result": result
    }
