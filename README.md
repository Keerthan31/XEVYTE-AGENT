# Xevyte Connect AI Agent

An enterprise conversational AI agent built for the **Xevyte Connect** ecosystem. It enables employees, managers, and HR/Operations teams to execute workflows, manage tasks, and retrieve company information via natural language chat.

---

## 🌟 Key Capabilities

The agent integrates with the core Xevyte Connect backend APIs and provides automated, role-aware execution across multiple organizational modules:

* **Time & Attendance:** Apply for leaves, query leave balances, log daily attendance, and process manager approvals/rejections.
* **Claims & Reimbursements:** Multi-category expense claiming (Travel, Hotel, Meals, Conveyance, General), receipt parsing, draft saving, and claim status tracking.
* **Travel Desk:** Flight/train/hotel travel requests, ticket retrieval, and manager itinerary approvals.
* **Salary & Compensation:** Monthly payslip retrieval, salary revision history, and compensation structure queries.
* **Asset Management:** Asset inventory search, employee asset allocation, and offboarding returns.
* **Employee Lifecycle & Exits:** Resignation processing, Last Working Day (LWD) management, and multi-department exit clearances.
* **Service Desk & Ticketing:** IT and HR support ticket creation, priority updates, and resolution workflows.
* **Contracts & SOWs:** Statement of Work uploads and client document management.
* **Performance Management:** Goal setting, progress tracking, and employee appraisal submissions.
* **Policy RAG (Retrieval-Augmented Generation):** Semantic and BM25 hybrid search over company HR and operational policy documents via ChromaDB.

---

## 🏛️ System Architecture

```text
                     +---------------------------------------+
                     |           Frontend UI (React)         |
                     |  - Adaptive Forms & Capability Grid   |
                     |  - Multi-session Chat & Live Stream   |
                     +-------------------+-------------------+
                                         |
                                         | HTTP / REST (JWT Auth)
                                         v
                     +---------------------------------------+
                     |         Backend Gateway (FastAPI)     |
                     |  - Auth Verification & Guardrails     |
                     |  - Session & Conversation Memory      |
                     +-------------------+-------------------+
                                         |
               +-------------------------+-------------------------+
               |                                                   |
               v                                                   v
+-----------------------------+                     +-----------------------------+
|    Agent Engine (LangGraph) |                     |      Policy RAG Engine      |
|  - LLM Orchestration        |                     |  - ChromaDB Vector Store    |
|  - Confirmation Protocol    |                     |  - Document Chunking / BM25 |
|  - Dynamic Tool Execution   |                     |  - Hybrid Semantic Search   |
+--------------+--------------+                     +-----------------------------+
               |
               v
+---------------------------------------------------------------------------------+
|                         Dynamic API Tool Catalog                                |
|  - config/XEVYTE_API_CATALOG.json (Schemas, Endpoints & Role Constraints)       |
+----------------------------------------+----------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |      Xevyte Connect Core Backend      |
                     |        (Spring Boot REST API)         |
                     +---------------------------------------+
```

---

## 📁 Repository Structure

```text
XEVYTE-AGENT-main/
├── app/                              # Backend FastAPI Application
│   ├── agent/                        # LangGraph Engine, Confirmation flows & Tool execution
│   │   ├── confirmation.py           # Two-phase transaction confirmation handler
│   │   ├── engine.py                 # Core agent graph & execution loop
│   │   ├── file_parser.py            # PDF / image / text parser for uploaded context
│   │   ├── memory.py                 # Persistent chat history
│   │   ├── system_prompt.py          # Enterprise agent prompt & instructions
│   │   └── tools.py                  # Dynamic tool generator from API catalog
│   ├── auth/                         # Security & Authentication
│   │   ├── guardrails.py             # Input safety & prompt injection filters
│   │   └── jwt_handler.py            # Token validation & claims extraction
│   ├── catalog/                      # API Catalog Management
│   │   ├── loader.py                 # Loads & parses XEVYTE_API_CATALOG.json
│   │   ├── models.py                 # Catalog data schemas
│   │   └── search.py                 # Tool lookup & similarity search
│   ├── db/                           # Database Layer
│   │   ├── database.py               # Async SQLAlchemy engine
│   │   └── models.py                 # Chat sessions & message records
│   ├── middleware/                   # Request / response middleware
│   ├── rag/                          # Retrieval-Augmented Generation
│   │   ├── indexer.py                # Policy indexing pipeline into ChromaDB
│   │   ├── retriever.py              # Hybrid BM25 + Vector retriever
│   │   └── policies/                 # Policy documents (PDF / TXT)
│   ├── routes/                       # API Endpoints
│   │   ├── chat.py                   # Chat streaming & execution
│   │   ├── reminders.py              # Scheduled notification endpoints
│   │   └── sessions.py               # Session history & management
│   ├── scheduler/                    # Background Jobs & Notifications
│   │   ├── email_service.py          # Email dispatcher for notifications
│   │   ├── runner.py                 # Async scheduler runner
│   │   └── tasks.py                  # Scheduled tasks (reminders, sync)
│   ├── config.py                     # Pydantic application settings
│   └── main.py                       # FastAPI application entrypoint
├── certs/                            # SSL certificates & generation scripts
├── config/
│   └── XEVYTE_API_CATALOG.json       # Dynamic API schema catalog used by Agent tools
├── frontend/                         # React + Vite Frontend Application
│   ├── assets/                       # UI images and branding
│   ├── src/                          # React components & UI logic
│   ├── package.json                  # Node dependencies
│   └── vite.config.js                # Vite build configuration
├── tests/                            # Automated Pytest Suite
│   ├── conftest.py                   # Test fixtures & mocks
│   ├── test_api_tools.py             # Tool invocation tests
│   ├── test_functional.py            # End-to-end user workflows
│   ├── test_hallucination.py         # Grounding & hallucination guards
│   ├── test_integration.py           # Backend proxy integration
│   ├── test_intent.py                # Intent classification accuracy
│   ├── test_multi_turn.py            # Multi-turn context retention
│   ├── test_negative.py              # Error handling & invalid inputs
│   ├── test_parameters.py            # Payload validation tests
│   ├── test_performance.py           # Latency & throughput tests
│   ├── test_regression.py            # Regression prevention
│   ├── test_security.py              # Auth & prompt injection safety
│   └── test_uat.py                   # User Acceptance Testing
├── Dockerfile                        # Production container build definition
├── docker-compose.yml                # Docker compose orchestration
├── requirements.txt                  # Python dependencies
├── .dockerignore                     # Docker build exclusions
└── .gitignore                        # Git exclusions
```

---

## ⚙️ Environment Configuration

Create a `.env` file in the root directory (refer to [`.env.example`](file:///.env) if present, or set the following variables):

```ini
# --- LLM Settings ---
OPENAI_API_KEY=your_openai_api_key
MODEL_NAME=gpt-4o

# --- Database ---
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/xevyte_agent

# --- Backend Integration ---
SCALOZ_BACKEND_URL=https://backend.xevyte.internal
SCALOZ_ENCRYPTION_KEY=your_secure_encryption_key

# --- Security ---
JWT_SECRET_KEY=your_jwt_secret_key
CONFIRMATION_SECRET_KEY=your_confirmation_signing_key

# --- RAG ---
CHROMA_PERSIST_DIR=data/chroma
RAG_POLICIES_DIR=app/rag/policies
```

---

## 🚀 Getting Started

### Option 1: Running with Docker (Recommended for Deployment)

Build and run using Docker Compose:
```bash
docker-compose up --build -d
```
The agent backend will start on `http://localhost:8443` (or `https://localhost:8443` if SSL certificates are mounted).

---

### Option 2: Running Locally

#### 1. Backend Setup
1. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   # Linux/macOS:
   source .venv/bin/activate
   # Windows:
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
   The backend will be available at `http://localhost:8000`.

#### 2. Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   npm install
   ```
2. Start the development server:
   ```bash
   npm run dev
   ```
   The web application will be accessible at `http://localhost:5173`.

---

## 🧪 Running Automated Tests

Run the full pytest suite from the root directory:

```bash
pytest tests/ -v
```

To run a specific test suite:
```bash
# Security & prompt injection tests
pytest tests/test_security.py -v

# Intent classification tests
pytest tests/test_intent.py -v

# Functional workflow tests
pytest tests/test_functional.py -v
```

---

## 🔒 Security & Confirmation Flow

Sensitive actions (e.g., submitting resignation, finalizing claims, approving high-value travel requests) follow a **Two-Phase Confirmation Protocol**:
1. **Proposal Phase:** The agent validates the payload against `XEVYTE_API_CATALOG.json` and issues a signed confirmation token with an action summary.
2. **Execution Phase:** The user confirms the prompt via UI, and the signed token is submitted back to execute the API call with zero hallucination.
