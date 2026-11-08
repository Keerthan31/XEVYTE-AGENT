import logging
from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional
import httpx

from app.config import get_settings
from app.scheduler.email_service import (
    send_checkin_reminder_email,
    send_checkout_reminder_email,
    send_pending_approvals_digest_email,
)

logger = logging.getLogger("xeva.scheduler.tasks")

IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now() -> datetime:
    return datetime.now(IST)

async def is_holiday_or_weekend(target_date: Optional[date] = None) -> Tuple[bool, str]:
    """
    Checks whether target_date (defaults to today in IST) is a weekend or company holiday.
    Returns: (is_skip, reason)
    """
    if target_date is None:
        target_date = get_ist_now().date()

    # 1. Weekend Check (Monday is 0, Sunday is 6)
    if target_date.weekday() >= 5:
        day_name = target_date.strftime("%A")
        return True, f"Weekend ({day_name})"

    # 2. Company Holiday Check via Java Backend
    settings = get_settings()
    year = target_date.year
    date_str = target_date.strftime("%Y-%m-%d")
    date_ddmmyyyy = target_date.strftime("%d-%m-%Y")

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(f"{settings.HRMS_API_BASE_URL}/api/leaves/holidays/year/{year}")
            if resp.is_success:
                holidays = resp.json()
                if isinstance(holidays, list):
                    for h in holidays:
                        h_date = h.get("holidayDate") or h.get("date") or ""
                        h_name = h.get("holidayName") or h.get("name") or "Company Holiday"
                        if h_date in (date_str, date_ddmmyyyy):
                            return True, f"Company Holiday: {h_name}"
    except Exception as e:
        logger.warning(f"Could not check company holiday calendar from Java: {e}")

    return False, "Working Day"

async def fetch_active_employees() -> List[Dict[str, Any]]:
    """
    Fetches the list of active employees from Java HRMS with work emails.
    """
    settings = get_settings()
    employees = []

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # Check employees / applicants / tenant directory
            resp = await client.get(f"{settings.HRMS_API_BASE_URL}/api/v1/applicants")
            if resp.is_success and isinstance(resp.json(), list):
                for emp in resp.json():
                    emp_id = emp.get("employeeId") or emp.get("applicantId")
                    work_email = emp.get("email") or emp.get("workMail")
                    first_name = emp.get("firstName") or ""
                    last_name = emp.get("lastName") or ""
                    full_name = f"{first_name} {last_name}".strip() or emp.get("name") or emp_id

                    if emp_id and work_email and "@" in work_email:
                        employees.append({
                            "employeeId": emp_id,
                            "name": full_name,
                            "workEmail": work_email,
                            "role": emp.get("role", "EMPLOYEE")
                        })
    except Exception as e:
        logger.warning(f"Could not fetch directory from applicants endpoint: {e}")

    # Fallback to known active employees / admins if directory was empty
    if not employees:
        employees.append({
            "employeeId": "scaloz_admin",
            "name": "Admin User",
            "workEmail": "admin@xevyte.com",
            "role": "ADMIN"
        })

    return employees

async def run_morning_checkin_reminders(force: bool = False) -> Dict[str, Any]:
    """
    Morning job: Sends Check-In reminder strictly to company email for employees who haven't punched in today.
    """
    now = get_ist_now()
    today_str = now.strftime("%d-%m-%Y")
    today_iso = now.strftime("%Y-%m-%d")

    is_skip, reason = await is_holiday_or_weekend(now.date())
    if is_skip and not force:
        logger.info(f"Skipping Morning Check-In Reminders: {reason}")
        return {"status": "skipped", "reason": reason, "date": today_str}

    employees = await fetch_active_employees()
    settings = get_settings()
    sent_count = 0
    skipped_count = 0
    details = []

    async with httpx.AsyncClient(timeout=8.0) as client:
        for emp in employees:
            emp_id = emp["employeeId"]
            work_email = emp["workEmail"]
            name = emp["name"]

            has_checked_in = False
            try:
                # Check attendance record for today
                res = await client.get(f"{settings.HRMS_API_BASE_URL}/api/daily-entry/employee/{emp_id}")
                if res.is_success and isinstance(res.json(), list):
                    for entry in res.json():
                        e_date = entry.get("date") or ""
                        if e_date.startswith(today_iso) or e_date.startswith(today_str):
                            if entry.get("loginTime") or entry.get("status") in ("PRESENT", "CHECKED_IN"):
                                has_checked_in = True
                                break
            except Exception as e:
                logger.debug(f"Could not verify attendance status for {emp_id}: {e}")

            if not has_checked_in:
                success = await send_checkin_reminder_email(name, work_email, today_str)
                if success:
                    sent_count += 1
                    details.append({"employeeId": emp_id, "email": work_email, "status": "sent"})
            else:
                skipped_count += 1
                details.append({"employeeId": emp_id, "email": work_email, "status": "already_checked_in"})

    logger.info(f"🌅 Morning Check-In Reminders: {sent_count} sent, {skipped_count} already checked in.")
    return {
        "status": "completed",
        "date": today_str,
        "sentCount": sent_count,
        "skippedCount": skipped_count,
        "details": details
    }

async def run_evening_checkout_reminders(force: bool = False) -> Dict[str, Any]:
    """
    Evening job: Sends Check-Out reminder to employees who checked in today but haven't punched out yet.
    """
    now = get_ist_now()
    today_str = now.strftime("%d-%m-%Y")
    today_iso = now.strftime("%Y-%m-%d")

    is_skip, reason = await is_holiday_or_weekend(now.date())
    if is_skip and not force:
        logger.info(f"Skipping Evening Check-Out Reminders: {reason}")
        return {"status": "skipped", "reason": reason, "date": today_str}

    employees = await fetch_active_employees()
    settings = get_settings()
    sent_count = 0
    skipped_count = 0
    details = []

    async with httpx.AsyncClient(timeout=8.0) as client:
        for emp in employees:
            emp_id = emp["employeeId"]
            work_email = emp["workEmail"]
            name = emp["name"]

            needs_checkout = False
            try:
                res = await client.get(f"{settings.HRMS_API_BASE_URL}/api/daily-entry/employee/{emp_id}")
                if res.is_success and isinstance(res.json(), list):
                    for entry in res.json():
                        e_date = entry.get("date") or ""
                        if e_date.startswith(today_iso) or e_date.startswith(today_str):
                            # Checked in but not yet checked out
                            if entry.get("loginTime") and not entry.get("logoutTime"):
                                needs_checkout = True
                                break
            except Exception as e:
                logger.debug(f"Could not verify check-out status for {emp_id}: {e}")

            if needs_checkout:
                success = await send_checkout_reminder_email(name, work_email, today_str)
                if success:
                    sent_count += 1
                    details.append({"employeeId": emp_id, "email": work_email, "status": "sent"})
            else:
                skipped_count += 1
                details.append({"employeeId": emp_id, "email": work_email, "status": "not_applicable"})

    logger.info(f"🌆 Evening Check-Out Reminders: {sent_count} sent, {skipped_count} skipped.")
    return {
        "status": "completed",
        "date": today_str,
        "sentCount": sent_count,
        "skippedCount": skipped_count,
        "details": details
    }

async def run_evening_approvals_digest(force: bool = False) -> Dict[str, Any]:
    """
    Evening job: Sends pending approvals digest to Managers & HR admins who have pending approval requests.
    """
    now = get_ist_now()
    today_str = now.strftime("%d-%m-%Y")

    employees = await fetch_active_employees()
    settings = get_settings()
    sent_count = 0
    details = []

    async with httpx.AsyncClient(timeout=8.0) as client:
        for emp in employees:
            emp_id = emp["employeeId"]
            work_email = emp["workEmail"]
            name = emp["name"]

            try:
                res = await client.get(f"{settings.HRMS_API_BASE_URL}/api/task-counts/{emp_id}")
                if res.is_success and isinstance(res.json(), dict):
                    counts = res.json()
                    total = counts.get("total", 0)
                    if total > 0:
                        success = await send_pending_approvals_digest_email(name, work_email, counts)
                        if success:
                            sent_count += 1
                            details.append({"employeeId": emp_id, "email": work_email, "pendingTotal": total, "status": "sent"})
            except Exception as e:
                logger.debug(f"Could not fetch task counts for {emp_id}: {e}")

    logger.info(f"📋 Evening Approvals Digest: {sent_count} manager digest emails sent.")
    return {
        "status": "completed",
        "date": today_str,
        "sentCount": sent_count,
        "details": details
    }
