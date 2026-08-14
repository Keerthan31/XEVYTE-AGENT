# Enterprise Upgrade (v2) — what's new

This zip contains BOTH the original working agent (unchanged, still at
`/api/agent/chat`) AND a new, more granular enterprise pipeline at
`/api/agent/v2/chat` built from the 36-section spec + architecture
diagrams. Nothing about v1 was touched — v2 is additive, in `app/planes/`
and `app/workflow/pipeline.py`.

## What's new, and REAL-TESTED (not scaffolding)

Every module below was tested against real data (the actual 633-endpoint
catalog, a real local Postgres, a real mock HTTP server standing in for
the HRMS backend) — only the OpenAI calls are mocked in tests, since this
sandbox has no network access to api.openai.com.

- **`app/planes/control/domain_router.py`** — 84 real modules clustered into
  18 domains, 100% coverage verified (zero unmapped modules).
- **`app/planes/control/context_engine.py`** — parameter provenance tracking.
  Every value tagged USER/SESSION/API_RESULT/MEMORY/SYSTEM/LLM_GUESS;
  fabricated source claims (e.g. "this came from your session" when it
  didn't) are independently cross-checked and downgraded to untrusted.
- **`app/planes/control/tool_discovery.py`** — hybrid retrieval: real BM25
  (rank-bm25) + semantic (Chroma) + domain metadata filter + weighted
  rerank, replacing the old pure-semantic retriever.
- **`app/planes/control/intent_engine.py`**, **`planner.py`**,
  **`response_generator.py`** — structured intent classification with
  confidence gating, tool selection + provenance-tagged param extraction,
  and a response generator that can only see validated results (never raw
  executor output).
- **`app/planes/knowledge/tool_registry.py`** — formal registry (633 tools:
  schema, risk, approval flag, idempotency, retry policy, content-hash
  version, owner, lifecycle status) built on top of the existing catalog.
- **`app/planes/governance/`** — missing-parameter gate, schema/type
  validation, deterministic policy engine (role/tenant/auth, fails closed
  on anything unparsed), 4-tier risk engine, and an approval service where
  every approval is bound to a **SHA-256 hash of the exact tool_id +
  arguments** — an approved action can't silently cover a different one if
  the plan changes before execution.
- **`app/planes/execution/execution_gate.py`** — the critical security
  boundary. Independently re-verifies all 10 preconditions from the spec's
  acceptance test; tested against every scenario in it, including the
  hash-mismatch case.
- **`app/planes/execution/api_fabric.py`** — wraps the original executor
  with a persisted per-module circuit breaker and idempotency-key
  protection (a retried write returns the cached result instead of firing
  twice). Tested against a real server: breaker trips OPEN after 5
  failures and genuinely blocks calls; a repeated DELETE hits the server
  exactly once.
- **`app/planes/execution/result_validator.py`**, **`error_recovery.py`** —
  standard `{success,data,error,tool_id,request_id,timestamp}` envelope;
  categorized failure handling (NETWORK/AUTH/VALIDATION/BUSINESS/...) each
  mapped to an explicit strategy, never a generic retry loop.
- **`app/mcp_server/server.py`** — real MCP server (the `mcp` SDK) exposing
  exactly three tools — `search_tools`, `get_tool_contract`, `execute_tool`
  — not 633. `execute_tool` is routed through the same execution_gate as
  the chat path; there is no MCP tool that calls the Java API directly.
- **`app/workflow/pipeline.py`** — wires all of the above into the actual
  18-step flow, with `workflow_runs` (Postgres) tracking each request
  through the named states (RECEIVED → UNDERSTANDING → ... → COMPLETED /
  FAILED / ESCALATED). Full pipeline integration-tested end-to-end.

## Deferred — needs real infra this sandbox can't stand up

Built as clean interfaces/lightweight local defaults, not faked as fully
production-deployed:

- **Event bus**: `event_log` table + an in-process publish path exist;
  swapping in real Kafka/RabbitMQ means replacing that one module behind
  the same interface.
- **Live OpenTelemetry/Prometheus/Grafana dashboards**: instrumentation
  points are there (every stage already logs to `workflow_runs`/
  `param_provenance_log`/`audit_log`); wiring an actual OTel exporter +
  standing up Prometheus/Grafana is an infra step for your environment.
- **Generic OAuth/OIDC**: the real auth need (Scaloz IAM's custom JWT SSO)
  is already fully handled — see the original README. Generic OIDC would
  only matter if that backend changed.
- **Durable, resumable execution mid-step** (LangGraph's Postgres
  checkpointer, installed and ready in requirements.txt): `workflow_runs`
  gives you the queryable state today; wiring the checkpointer for actual
  crash-and-resume mid-plan is the next increment, not done in this pass.

## Running v2

Same setup as the original README (`.env`, Postgres, catalog generation,
`scripts/ingest_catalog.py`), then hit `/api/agent/v2/chat` instead of
`/api/agent/chat`. Both routes work off the same catalog/session/auth
layer — nothing about login changes.
