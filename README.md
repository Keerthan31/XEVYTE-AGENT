# Xeva — Xevyte HRMS AI Agent

A conversational AI agent that lets employees interact with the **Xevyte Connect** HRMS platform through natural language. Built with **LangGraph + FastAPI + OpenRouter (free tier) + React**.

---

## Architecture

```
User ──► React UI (port 3000)
              │
              ▼
         FastAPI Backend (port 8001)
              │
         LangGraph ReAct Agent
              │
    ┌─────────┴──────────┐
    │   12 HRMS Tools    │
    └─────────┬──────────┘
              │
    Xevyte Connect APIs (port 8080)
```

---

## Features / Tools

| # | Tool | API Endpoint |
|---|------|-------------|
| 1 | Get leave balance | `GET /api/leaves/employee/{id}` |
| 2 | Get leave history | `GET /api/leaves/employee/{id}` |
| 3 | Apply for leave | `POST /api/leaves/apply-with-existing-file` |
| 4 | Cancel leave | `PUT /api/leaves/cancel/{id}` |
| 5 | Get payslips | `GET /api/payroll/payslips/employee/{id}` |
| 6 | Raise grievance | `POST /api/grievances/anonymous` |
| 7 | Submit helpdesk ticket | `POST /api/tickets/submit` |
| 8 | Get my tickets | `GET /api/tickets/my-tickets/{id}` |
| 9 | Get notifications | `GET /api/notifications/{id}` |
| 10 | Attendance summary | `GET /api/v1/analytics/me` |
| 11 | Employee profile | `GET /api/employees/{id}` |
| 12 | Task summary | `GET /api/task-counts/{id}` |

---

## Quick Start

### 1. Backend

```bash
cd backend
cp ../.env.example ../.env
# Edit .env — add OPENROUTER_API_KEY and XEVYTE_API_BASE

pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:3000
```

### 3. Docker (both services)

```bash
cp .env.example .env
# Fill in your values
docker-compose up --build
```

---

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Get free key at https://openrouter.ai |
| `OPENROUTER_MODEL` | Default: `meta-llama/llama-3.3-70b-instruct:free` |
| `XEVYTE_API_BASE` | URL of the running Xevyte Connect backend |

---

## Authentication

Xevyte Connect uses **Scaloz IAM** for SSO. The agent needs a valid JWT token:

1. Log in at the Scaloz IAM portal (`http://localhost:3001` or production URL)
2. Open DevTools → Application → LocalStorage, copy the JWT token
3. Paste it into the ⚙️ Settings panel in the chat UI

The token is sent as `Authorization: Bearer <token>` with every API call.

---

## Example Conversations

```
User: What's my leave balance?
Xeva: You currently have:
      • Casual Leave: 8 days remaining (12 granted, 4 consumed)
      • Sick Leave: 7 days remaining (7 granted, 0 consumed)
      • Earned Leave: 15 days remaining

User: Apply casual leave from 1st August to 3rd August, reason is personal work
Xeva: I'll apply Casual Leave from 01-08-2025 to 03-08-2025 (3 days) with
      reason "personal work". Shall I confirm?

User: Yes
Xeva: ✅ Leave applied successfully!
      Reference ID: LR-2025-0892
      Status: PENDING (awaiting manager approval)
```

---

## Project Structure

```
xevyte-hrms-agent/
├── backend/
│   ├── main.py          # FastAPI app + /chat endpoint
│   ├── agent.py         # LangGraph ReAct agent
│   ├── tools.py         # 12 HRMS tool functions
│   ├── config.py        # Env config
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.jsx               # Main chat UI
│   │   ├── api.js                # Backend API client
│   │   └── components/
│   │       ├── MessageBubble.jsx # Chat bubbles with markdown
│   │       ├── SettingsPanel.jsx # JWT + employee ID config
│   │       ├── Suggestions.jsx   # Quick-action chips
│   │       └── TypingIndicator.jsx
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```
