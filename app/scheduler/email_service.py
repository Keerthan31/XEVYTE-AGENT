import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional

from app.config import get_settings

logger = logging.getLogger("xeva.scheduler.email")

def get_base_html_template(title: str, preheader: str, content_html: str, action_url: Optional[str] = None, action_text: Optional[str] = None) -> str:
    """Standard responsive branded HTML email template for Xevyte Connect"""
    action_button_html = ""
    if action_url and action_text:
        action_button_html = f"""
        <table border="0" cellpadding="0" cellspacing="0" class="btn btn-primary" style="border-collapse: separate; mso-table-lspace: 0pt; mso-table-rspace: 0pt; width: 100%; box-sizing: border-box; min-width: 100% !important;" width="100%">
            <tbody>
                <tr>
                    <td align="center" style="font-family: sans-serif; font-size: 14px; vertical-align: top; padding-top: 24px; padding-bottom: 24px;">
                        <a href="{action_url}" target="_blank" style="display: inline-block; color: #ffffff; background-color: #008080; border: solid 1px #008080; border-radius: 8px; box-sizing: border-box; cursor: pointer; text-decoration: none; font-size: 14px; font-weight: bold; margin: 0; padding: 12px 28px; text-transform: capitalize; border-color: #008080; box-shadow: 0 4px 6px -1px rgba(0, 128, 128, 0.2);">{action_text}</a>
                    </td>
                </tr>
            </tbody>
        </table>
        """

    return f"""<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <title>{title}</title>
    <style>
      body {{
        background-color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        font-size: 14px;
        line-height: 1.6;
        margin: 0;
        padding: 0;
        color: #334155;
      }}
      .container {{
        display: block;
        margin: 0 auto !important;
        max-width: 580px;
        padding: 24px;
        width: 580px;
      }}
      .card {{
        background: #ffffff;
        border-radius: 16px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        overflow: hidden;
      }}
      .header {{
        background: linear-gradient(135deg, #004d40 0%, #008080 100%);
        padding: 24px 32px;
        text-align: left;
      }}
      .header h1 {{
        color: #ffffff;
        font-size: 20px;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.5px;
      }}
      .header p {{
        color: #b2dfdb;
        font-size: 12px;
        margin: 4px 0 0 0;
      }}
      .content {{
        padding: 32px;
      }}
      .footer {{
        padding: 20px 32px;
        text-align: center;
        font-size: 11px;
        color: #94a3b8;
        border-top: 1px solid #f1f5f9;
        background-color: #fafafa;
      }}
      .badge {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 600;
        background-color: #e6fffa;
        color: #00796b;
      }}
    </style>
  </head>
  <body>
    <span style="color: transparent; display: none; height: 0; max-height: 0; max-width: 0; opacity: 0; overflow: hidden; mso-hide: all; visibility: hidden; width: 0;">{preheader}</span>
    <div class="container">
      <div class="card">
        <div class="header">
          <h1>Xevyte Connect</h1>
          <p>Automated HRMS Notification</p>
        </div>
        <div class="content">
          {content_html}
          {action_button_html}
        </div>
        <div class="footer">
          <p style="margin: 0;">This is an automated notification from Xevyte HRMS. Please do not reply directly to this email.</p>
          <p style="margin: 4px 0 0 0;">&copy; 2026 Xevyte Technologies. All rights reserved.</p>
        </div>
      </div>
    </div>
  </body>
</html>
"""

async def send_work_email(to_email: str, subject: str, html_body: str, plain_body: Optional[str] = None) -> bool:
    """
    Sends an email strictly to the employee's work/company email address.
    If SMTP credentials are not configured, logs the dispatch with full payload.
    """
    if not to_email or "@" not in to_email:
        logger.warning(f"Skipping email delivery: invalid recipient email '{to_email}'")
        return False

    settings = get_settings()

    if not settings.SMTP_ENABLED or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.info(
            f"[SIMULATED EMAIL DISPATCH] (SMTP_ENABLED=False or credentials not set in .env)\n"
            f"To: {to_email}\n"
            f"Subject: {subject}\n"
            f"Preview: {plain_body or subject}"
        )
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL or settings.SMTP_USER}>"
        msg["To"] = to_email

        if plain_body:
            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Send via SMTP
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10.0) as server:
            if settings.SMTP_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL or settings.SMTP_USER, [to_email], msg.as_string())

        logger.info(f"✅ Successfully sent email to work address: {to_email} (Subject: '{subject}')")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to deliver email to {to_email}: {e}")
        return False

# ----------------------------------------------------------------------------
# Specific Notification Templates
# ----------------------------------------------------------------------------

async def send_checkin_reminder_email(employee_name: str, work_email: str, date_str: str) -> bool:
    """Send morning check-in reminder to an employee's work email."""
    subject = f"⏰ Morning Reminder: Daily Check-In for {date_str}"
    preheader = f"Hi {employee_name}, please remember to mark your attendance check-in for today."
    portal_url = "http://localhost:5173"

    content_html = f"""
    <h2 style="font-size: 18px; font-weight: 700; color: #1e293b; margin-top: 0;">Good Morning, {employee_name}! ☀️</h2>
    <p style="font-size: 14px; line-height: 1.6; color: #475569;">
      This is a quick reminder that your attendance check-in has not been recorded yet for today (<strong>{date_str}</strong>).
    </p>
    <div style="background-color: #f0fdfa; border-left: 4px solid #008080; padding: 14px 18px; border-radius: 6px; margin: 20px 0;">
      <p style="margin: 0; font-size: 13.5px; color: #115e59;">
        💡 <strong>Quick Check-In:</strong> You can check in instantly by chatting with <strong>Xeva</strong> or via the Xevyte Connect portal.
      </p>
    </div>
    <p style="font-size: 13px; color: #64748b; margin-bottom: 0;">
      If you are on an approved leave or working from a remote client location, you can update your status accordingly.
    </p>
    """
    
    plain_text = f"Good Morning, {employee_name}! This is a reminder to mark your attendance check-in for {date_str}. Visit: {portal_url}"
    html = get_base_html_template(subject, preheader, content_html, action_url=portal_url, action_text="Punch In with Xeva")
    return await send_work_email(work_email, subject, html, plain_text)

async def send_checkout_reminder_email(employee_name: str, work_email: str, date_str: str) -> bool:
    """Send evening check-out reminder to an employee's work email."""
    subject = f"🌙 Evening Reminder: Daily Check-Out for {date_str}"
    preheader = f"Hi {employee_name}, please remember to complete your check-out before leaving for the day."
    portal_url = "http://localhost:5173"

    content_html = f"""
    <h2 style="font-size: 18px; font-weight: 700; color: #1e293b; margin-top: 0;">Good Evening, {employee_name}! 🌆</h2>
    <p style="font-size: 14px; line-height: 1.6; color: #475569;">
      We noticed you checked in earlier today (<strong>{date_str}</strong>), but your check-out punch has not been recorded yet.
    </p>
    <div style="background-color: #eff6ff; border-left: 4px solid #3b82f6; padding: 14px 18px; border-radius: 6px; margin: 20px 0;">
      <p style="margin: 0; font-size: 13.5px; color: #1e40af;">
        ⏱️ <strong>Record Working Hours:</strong> Logging out ensures your working hours and daily attendance timesheet are accurately calculated.
      </p>
    </div>
    <p style="font-size: 13px; color: #64748b; margin-bottom: 0;">
      Simply open Xeva and type <em>"check out"</em> to record your logout time.
    </p>
    """

    plain_text = f"Good Evening, {employee_name}! Please remember to complete your check-out for today ({date_str}). Visit: {portal_url}"
    html = get_base_html_template(subject, preheader, content_html, action_url=portal_url, action_text="Punch Out with Xeva")
    return await send_work_email(work_email, subject, html, plain_text)

async def send_pending_approvals_digest_email(manager_name: str, work_email: str, counts: Dict[str, Any]) -> bool:
    """Send evening pending approvals digest to manager's work email."""
    total = counts.get("total", 0)
    subject = f"📋 Action Required: {total} Pending Approval Request(s)"
    preheader = f"Hi {manager_name}, you have {total} pending requests awaiting your review."
    portal_url = "http://localhost:5173"

    items_html = ""
    categories = [
        ("leaves", "🏖️ Leave Requests", counts.get("leaves", 0)),
        ("claims", "💳 Expense Claims", counts.get("claims", 0)),
        ("helpdesk", "🎫 HelpDesk Change Requests", counts.get("helpdesk", 0)),
        ("travel", "✈️ Travel Requests", counts.get("travel", 0)),
        ("regularization", "⏱️ Attendance Regularizations", counts.get("regularization", 0)),
        ("exit", "🚪 Resignation / Exit Reviews", counts.get("exit", 0)),
    ]

    for key, label, count in categories:
        if count > 0:
            items_html += f"""
            <tr style="border-bottom: 1px solid #f1f5f9;">
              <td style="padding: 10px 14px; font-size: 13.5px; color: #334155;">{label}</td>
              <td style="padding: 10px 14px; text-align: right; font-weight: 700; font-size: 14px; color: #008080;">{count}</td>
            </tr>
            """

    content_html = f"""
    <h2 style="font-size: 18px; font-weight: 700; color: #1e293b; margin-top: 0;">Hello {manager_name},</h2>
    <p style="font-size: 14px; line-height: 1.6; color: #475569;">
      Here is your daily digest of pending team approval requests awaiting your review in Xevyte HRMS:
    </p>
    <div style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; margin: 20px 0; background: #ffffff;">
      <table style="width: 100%; border-collapse: collapse; text-align: left;">
        <thead>
          <tr style="background-color: #f8fafc; border-bottom: 2px solid #e2e8f0;">
            <th style="padding: 10px 14px; font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase;">Category</th>
            <th style="padding: 10px 14px; font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase; text-align: right;">Pending</th>
          </tr>
        </thead>
        <tbody>
          {items_html}
        </tbody>
      </table>
    </div>
    <p style="font-size: 13px; color: #64748b; margin-bottom: 0;">
      You can review and approve these directly with Xeva (e.g. <em>"Show pending leave approvals"</em>) or from the portal.
    </p>
    """

    plain_text = f"Hello {manager_name}, you have {total} pending approval requests awaiting review. Visit: {portal_url}"
    html = get_base_html_template(subject, preheader, content_html, action_url=portal_url, action_text="Review in Xevyte HRMS")
    return await send_work_email(work_email, subject, html, plain_text)
