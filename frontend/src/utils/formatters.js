export const TOOL_THOUGHT_MAPPING = {
  get_leave_balance: "Checking available leave balance...",
  get_leave_history: "Searching leave history database...",
  get_approved_leave_dates: "Checking approved leave dates...",
  apply_leave: "Drafting leave application...",
  cancel_leave: "Cancelling leave request...",
  get_pending_approvals: "Checking pending approvals...",
  action_leave: "Processing leave action...",
  get_attendance_summary: "Generating attendance analytics...",
  check_today_attendance: "Verifying today's attendance...",
  mark_attendance: "Marking attendance record...",
  submit_ticket: "Creating helpdesk ticket...",
  get_my_tickets: "Retrieving ticket status...",
  raise_grievance: "Filing confidential grievance...",
  get_notifications: "Fetching unread notifications...",
  mark_notification_read: "Updating notification status...",
  get_my_profile: "Accessing employee profile...",
  get_task_summary: "Compiling pending tasks...",
  get_holidays: "Checking company holiday calendar...",
};

export function getThoughtText(toolName) {
  return TOOL_THOUGHT_MAPPING[toolName] || `Executing ${toolName.replace(/_/g, ' ')}...`;
}
