# Xeva — Xevyte HRMS AI Agent

A production-grade conversational AI agent that lets employees interact with the **Xevyte Connect** HRMS platform through natural language. Built with **LangGraph + FastAPI + PostgreSQL + Pydantic v2 + Guardrails AI + GPT-4o + React (Vite & TailwindCSS)**.

---

## Architecture

```
User ──► React UI (Vite - port 3008 / 5173)
              │
              ▼
         FastAPI Backend (port 8001) ──► Guardrails & PII Masking
              │                              │
     ┌────────┴────────┐              Rate Limiter (10 req/60s)
     │                 │
PostgreSQL DB     LangGraph ReAct Agent
(Chat Sessions    (GPT-4o + gpt-3.5-turbo Failover)
 & Messages)           │
                  ┌────┴────────────────┐
                  │  24 HRMS Tools      │ (Structured JSON + TTL Cache)
                  └────┬────────────────┘
                       │
            Xevyte Connect REST APIs (port 8082)
```

---

## Enterprise Features & Capabilities

- 💬 **Natural Conversation**: Multi-turn conversational state powered by LangGraph ReAct framework with session memory (last 10 messages).
- 📦 **Structured Tool Outputs**: All 24 tools return standardized JSON envelopes (`success`, `message`, `data`, `metadata` with `exec_time_ms`).
- 🛡️ **Pydantic v2 Validation**: Enforces strict argument schemas (`ApplyLeaveInput`, `MarkAttendanceInput`, `SubmitTicketInput`, `ActionLeaveInput`, `UpdatePersonalDetailsInput`, `UpdateBankDetailsInput`, `AddNomineeInput`, `UpdateEmployeeBioInput`) before REST API calls.
- ⚡ **HTTP Resilience & Retries**: Tenacity-powered exponential backoff retries with automatic connection pooling for transient network errors and 5xx responses.
- 🚀 **In-Memory TTL Caching**: Thread-safe 30s TTL cache for read-only query APIs (`get_leave_balance`, `get_my_profile`, `get_holidays`, `get_my_allocations`, `get_my_nominees`).
- 🔒 **Enterprise Guardrails**: Prompt injection blocking, PII masking (JWT tokens, passwords), and output sanitization preventing internal API URL leakage.
- 🔄 **Multi-Model Failover**: Seamless automatic failover from GPT-4o → GPT-3.5 Turbo during rate limits or outages.
- 🚦 **Rate Limiting**: Sliding-window rate limiter (configurable via `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW` env vars) to prevent API abuse.
- 📊 **LangSmith Observability**: Optional real-time telemetry tracing, token consumption metrics, and tool execution latency monitoring.
- 🗄️ **PostgreSQL Session Memory**: Persists chat sessions and message histories with optimized JOIN queries and database indexes.
- 🏥 **Health Dashboard**: `/health` endpoint validates DB connectivity, OpenAI API status, active model, and rate limit configuration.
- 🧪 **Test Suites**: Includes `test_agent_suite.py` and `test_deepeval_agent.py` with dynamic runtime test payloads.

---

## HRMS Tool Capabilities (24 Tools)

| Category | Available Agent Tools |
|---|---|
| **Leave Management** | `get_leave_balance`, `get_leave_history`, `get_approved_leave_dates`, `apply_leave`, `cancel_leave`, `get_pending_approvals`, `action_leave` |
| **Attendance & Time** | `get_attendance_summary`, `check_today_attendance`, `mark_attendance` |
| **Helpdesk & IT** | `submit_ticket`, `get_my_tickets` |
| **Grievance & Alerts** | `raise_grievance`, `get_notifications`, `mark_notification_read` |
| **Profile & System** | `get_my_profile`, `get_task_summary`, `get_holidays`, `get_my_allocations` |
| **Self-Service Updates** | `update_personal_details`, `update_bank_details`, `get_my_nominees`, `add_nominee`, `update_employee_bio` |

---

## Quick Start

### Prerequisites
- **Python 3.10+**
- **Node.js 18+**
- **PostgreSQL Database** (running locally or remotely)
- **OpenAI API Key** (GPT-4o recommended)

---

### 1. Environment Setup

Copy `.env.example` to `.env` in the root directory:

```bash
cp .env.example .env
```

Configure your `.env` variables:
```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o
XEVYTE_API_BASE=http://localhost:8082

DB_NAME=scaloz_super_admin
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_HOST=127.0.0.1
DB_PORT=5432

# Optional: Rate Limiting (defaults: 10 requests per 60 seconds)
# RATE_LIMIT_MAX=10
# RATE_LIMIT_WINDOW=60

# Optional: LangSmith Tracing
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=your_langsmith_api_key_here
# LANGCHAIN_PROJECT=Xevyte-HRMS-Agent
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
> The server will automatically create required PostgreSQL chat tables (`xeva_chat_sessions` and `xeva_chat_messages`) with performance indexes on startup.

---

### 3. Frontend Setup

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite dev server
npm run dev
```
> Open your browser at `http://localhost:3008` (Vite proxy routes `/chat`, `/api`, `/health` to backend automatically).

---

### 4. Docker Deployment

```bash
docker-compose up --build
```

---

### 5. Health Check

```bash
curl http://localhost:8001/health
```

Response:
```json
{
  "status": "ok",
  "version": "2.6.0",
  "database": "connected",
  "openai": {
    "status": "connected",
    "model": "gpt-4o"
  },
  "resilience": {
    "max_http_retries": 3,
    "cache_ttl_seconds": 30,
    "rate_limit": "10 req / 60s per employee",
    "structured_outputs": true,
    "guardrails": true
  }
}
```

---

## Project Structure

```
xevyte-hrms-agent/
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules (excludes .env, node_modules, __pycache__)
├── README.md                 # Project documentation
├── docker-compose.yml        # Multi-container Docker Compose setup
├── backend/
│   ├── main.py               # FastAPI entrypoint, rate limiter, trace ID middleware & SSE streams
│   ├── agent.py              # LangGraph ReAct agent, system prompt & guardrail evaluation
│   ├── tools.py              # 24 HRMS tool functions with Pydantic schemas, TTL caching & retries
│   ├── guardrails.py         # PII masking & prompt injection safety module
│   ├── db.py                 # PostgreSQL connection pool, JOIN queries & session management
│   ├── config.py             # Environment configuration & multi-model failover array
│   ├── test_agent_suite.py   # Dynamic enterprise test suite
│   ├── test_deepeval_agent.py# DeepEval framework test suite
│   ├── requirements.txt      # Python dependencies
│   └── Dockerfile            # Backend Docker build script
└── frontend/
    ├── package.json          # Node dependencies and scripts
    ├── vite.config.js        # Vite configuration with backend proxy
    ├── Dockerfile            # Frontend Docker build (Nginx)
    └── src/
        ├── App.jsx           # Main chat canvas with throttled streaming & sidebar
        ├── api.js            # Axios & SSE streaming API client
        ├── main.jsx          # React entry point
        ├── index.css         # Global styles
        └── components/
            ├── Sidebar.jsx        # ChatGPT-style session history sidebar
            ├── Login.jsx          # Scaloz IAM encrypted login (AES-GCM)
            ├── MessageBubble.jsx  # Markdown message bubble with copy & form rendering
            ├── ThoughtProcess.jsx # AI thinking/tool execution status indicator
            ├── LeaveForm.jsx      # Interactive leave request form
            ├── TicketForm.jsx     # Interactive helpdesk ticket form
            └── TypingIndicator.jsx# Animated AI typing dots
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | System health (DB, OpenAI, rate limits) |
| `POST` | `/chat` | Synchronous agent chat |
| `POST` | `/chat/stream` | SSE streaming agent chat |
| `GET` | `/api/chats/sessions/{employee_id}` | Get all chat sessions |
| `POST` | `/api/chats/sessions` | Create/update session |
| `POST` | `/api/chats/sessions/{id}/messages` | Add message to session |
| `PUT` | `/api/chats/sessions/{id}/pin` | Pin/unpin session |
| `PUT` | `/api/chats/sessions/{id}/rename` | Rename session |
| `DELETE` | `/api/chats/sessions/{id}` | Delete session |
| `POST` | `/debug/tool` | Direct tool execution (dev only) |

---

## License

© 2026 Xevyte Technologies Pvt. Ltd. All rights reserved.
