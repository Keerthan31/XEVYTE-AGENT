# Xevyte Connect Agent

Xevyte Connect Agent is an intelligent, conversational AI assistant designed to seamlessly integrate with the **Xevyte Connect** platform. It helps employees, managers, and HR/Admins execute tasks and find information across various HR, IT, and Operations domains through a natural chat interface.

## 🚀 Features & Capabilities

The agent operates across multiple organizational domains by interacting with the Xevyte Connect backend APIs. Key capabilities include:

* **Time & Attendance:** Log daily entries, apply for leaves, check leave balances, and allow managers to approve/reject requests.
* **Reimbursements (Claims):** Draft expense claims by parsing receipts, submit claims, and check approval or finance processing statuses.
* **Travel:** Create travel requests, retrieve booked tickets, and help managers approve itineraries.
* **Salary & Compensation:** Retrieve payslips, check salary revision history, and assist HR in finalizing compensation structures.
* **Assets:** Query inventory, assign assets to employees, and process offboarding asset returns.
* **Exits:** Orchestrate resignation submissions, assist managers in adjusting LWDs (Last Working Days), and coordinate HR/IT clearances.
* **Support & Tickets:** Submit IT/HR helpdesk tickets, check ticket status, and allow admins to assign or resolve issues.
* **Contracts (SOWs):** Upload Statements of Work and retrieve project documents for customers.
* **Performance:** Assist managers in assigning goals, tracking progress, and help employees submit self-assessments during appraisal cycles.

## 🏗️ Architecture

The project consists of a Python-based AI Backend and a React-based Frontend.

* **Backend (FastAPI):**
  * Houses the core Agent Engine, Tool schemas, and System Prompts.
  * Uses **ChromaDB** for vector storage and Retrieval-Augmented Generation (RAG) to answer policy-related queries.
  * Connects directly to the Xevyte Connect Spring Boot backend.
* **Frontend (React + Vite):**
  * Modern, responsive chat UI built with React, TailwindCSS, and Vite.
  * Features adaptive forms, thought process indicators, and enterprise capability grids.

## 🛠️ Getting Started

### Prerequisites
* Python 3.9+
* Node.js 18+
* Xevyte Connect Backend (Spring Boot) running locally or accessible via network.

### 1. Setting up the Backend
Navigate to the root directory and install Python dependencies:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
Run the FastAPI server:
```bash
python -m app.main
```
The backend will start running on `http://localhost:8000`.

### 2. Setting up the Frontend
Navigate to the frontend directory, install dependencies, and start the Vite dev server:
```bash
cd frontend
npm install
npm run dev
```
The chat interface will be available at `http://localhost:5173`.

## 📁 Project Structure

```text
XEVYTE-AGENT-main/
├── app/                  # FastAPI Backend Code
│   ├── agent/            # LLM Engine, System Prompts, and Tools
│   ├── auth/             # Authentication & Guardrails
│   ├── catalog/          # Service catalog & API mappings
│   ├── db/               # Local database models & connections
│   ├── rag/              # RAG implementation (Indexer, Retriever, Policies)
│   ├── routes/           # FastAPI routers (Chat, Auth, Sessions)
│   └── main.py           # Application Entrypoint
├── frontend/             # React/Vite Frontend
│   ├── src/
│   │   ├── components/   # UI Components (MessageBubble, Sidebar, Forms)
│   │   ├── utils/        # Formatters and Helpers
│   │   ├── api.js        # API client to talk to FastAPI
│   │   ├── App.jsx       # Main Chat Interface
│   │   └── main.jsx      # React Entrypoint
│   ├── tailwind.config.js
│   └── vite.config.js
├── chroma_db/            # Vector Database storage (git-ignored)
└── requirements.txt      # Python dependencies
```
