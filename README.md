# Xeva — Xevyte HRMS AI Agent

A production-grade conversational AI agent that lets employees interact with the **Xevyte Connect** HRMS platform through natural language. Built with **LangGraph + FastAPI + PostgreSQL + Pydantic v2 + Guardrails AI + OpenRouter / LiteLLM + React (Vite & TailwindCSS)**.

---

## Architecture

```
User ──► React UI (Vite - port 5173 / 3000)
              │
              ▼
         FastAPI Backend (port 8001) ──► Guardrails & PII Masking
              │
    ┌─────────┴─────────┐
    │                   │
PostgreSQL DB      LangGraph ReAct Agent
(Chat Sessions &   (Pydantic Validation & LiteLLM Failover)
 Message History)       │
                   ┌────┴───────────────┐
                   │  18 HRMS Tools    │ (Structured JSON Responses)
                   └────┬───────────────┘
                        │
             Xevyte Connect REST APIs (port 8082)
```

---

## Enterprise Features & Capabilities

- 💬 **Natural Conversation**: Multi-turn conversational state powered by LangGraph ReAct framework.
- 📦 **Structured Tool Outputs**: All 18 tools return standardized JSON envelopes (`success`, `message`, `data`, `metadata`).
- 🛡️ **Instructor & Pydantic v2 Validation**: Enforces strict argument schemas (`ApplyLeaveInput`, `MarkAttendanceInput`, `SubmitTicketInput`, `ActionLeaveInput`) before REST API calls.
- ⚡ **HTTP Resilience & Retries**: Automatic connection pooling and exponential backoff retries (`0.5s, 1s, 2s`) for transient network errors.
- 🚀 **In-Memory TTL Caching**: Thread-safe 30s TTL cache for read-only query APIs (`get_leave_balance`, `get_my_profile`, `get_holidays`).
- 🔒 **Guardrails AI & PII Masking**: Automatically masks JWT tokens, passwords, and PII from log streams while blocking prompt injections.
- 🔄 **LiteLLM Multi-Model Failover**: Seamless automatic failover between LLM providers during OpenRouter rate limits or outages.
- 📊 **LangSmith Observability**: Real-time telemetry tracing, token consumption metrics, and tool execution latency monitoring.
- 🗄️ **PostgreSQL Session Memory**: Automatically persists chat sessions, message histories, and pinned threads.
- 🧪 **Dynamic Test Suites**: Includes `test_agent_suite.py` and `test_deepeval_agent.py` generating dynamic runtime test payloads with zero static data.

---

## HRMS Tool Capabilities

| Category | Available Agent Tools |
|---|---|
| **Leave Management** | `get_leave_balance`, `get_leave_history`, `get_approved_leave_dates`, `apply_leave`, `cancel_leave`, `get_pending_approvals`, `action_leave` |
| **Attendance & Time** | `get_attendance_summary`, `check_today_attendance`, `mark_attendance` |
| **Helpdesk & IT** | `submit_ticket`, `get_my_tickets` |
| **Grievance & Alerts** | `raise_grievance`, `get_notifications`, `mark_notification_read` |
| **Profile & System** | `get_my_profile`, `get_task_summary`, `get_holidays` |

---

## Quick Start

### Prerequisites
- **Python 3.10+**
- **Node.js 18+**
- **PostgreSQL Database** (running locally or remotely)

---

### 1. Environment Setup

Copy `.env.example` to `.env` in the root directory:

```bash
cp .env.example .env
```

Configure your `.env` variables:
```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=openrouter/free
XEVYTE_API_BASE=http://localhost:8082

DB_NAME=scaloz_super_admin
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_HOST=127.0.0.1
DB_PORT=5432

# Optional LangSmith Tracing
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=your_langsmith_api_key_here
LANGCHAIN_PROJECT=Xevyte-HRMS-Agent
```

---

### 2. Backend Setup & Testing

```bash
cd backend

# Install Python dependencies
pip install -r requirements.txt

# Run dynamic enterprise test suite
python3 test_agent_suite.py
python3 test_deepeval_agent.py

# Start FastAPI server
uvicorn main:app --reload --port 8001
```
> The server will automatically create required PostgreSQL chat tables (`xeva_chat_sessions` and `xeva_chat_messages`) on startup.

---

### 3. Frontend Setup

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite dev server
npm run dev
```
> Open your browser at `http://localhost:5173` (or `http://localhost:3000`).

---

### 4. Docker Deployment

```bash
docker-compose up --build
```

---

## Project Structure

```
xevyte-hrms-agent/
├── .env.example              # Environment variables template
├── README.md                 # Project documentation
├── docker-compose.yml        # Multi-container docker compose setup
├── backend/
│   ├── main.py               # FastAPI entrypoint, Trace ID middleware & SSE streams
│   ├── agent.py              # LangGraph ReAct agent & guardrail evaluation
│   ├── tools.py              # 18 HRMS tool functions with Pydantic schemas & TTL caching
│   ├── guardrails.py         # PII masking & prompt injection safety module
│   ├── db.py                 # PostgreSQL connection pool & session queries
│   ├── config.py             # Environment configuration & LiteLLM failover models
│   ├── test_agent_suite.py   # Dynamic enterprise test suite
│   ├── test_deepeval_agent.py# DeepEval & framework test suite
│   ├── requirements.txt      # Python dependencies
│   └── Dockerfile            # Backend Docker build script
└── frontend/
    ├── package.json          # Node dependencies and scripts
    ├── vite.config.js        # Vite configuration
    ├── Dockerfile            # Frontend Docker build script
    └── src/
        ├── App.jsx           # Main chat canvas layout & sidebar controller
        ├── api.js            # Axios & SSE streaming API client
        └── components/
            ├── Sidebar.jsx   # ChatGPT-style chat session history sidebar
            ├── Login.jsx     # Scaloz IAM authentication login screen
            ├── MessageBubble.jsx # Markdown message bubble renderer
            ├── LeaveForm.jsx # Interactive leave request component
            ├── TicketForm.jsx# Interactive helpdesk ticket component
            └── TypingIndicator.jsx # Animated AI typing status
```
