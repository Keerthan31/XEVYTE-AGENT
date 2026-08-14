# Xevyte Connect HRMS Agent

A single conversational agent over the **entire** Xevyte Connect HRMS API —
**633 endpoints auto-discovered across 84 modules**, driven by natural
language, using the same Scaloz IAM login as the real app.

No endpoint is hardcoded. The agent works by *retrieving* the handful of
relevant endpoints for a given request (RAG over an auto-generated catalog)
and *executing* whichever one fits through one generic HTTP call layer —
so it covers everything the Java backend exposes today, and picks up new
endpoints automatically the next time you re-run the parser.

```
Natural language  ──▶  RAG retrieve (top ~12 of 633)  ──▶  LLM picks ONE + fills args
                                                                     │
        reply  ◀──  LLM explains result  ◀──  generic HTTP executor ◀──  guardrails
                                                     │                  (risk tier,
                                                     ▼                  confirm if needed)
                                          Xevyte Connect backend
                                       (caller's own Scaloz IAM token)
```

## Why this architecture (not 600+ hardcoded tools)

Handing an LLM 600+ function definitions at once doesn't work well —
function-calling quality degrades hard well before that count, and most of
the schema is irrelevant to any single request anyway. Instead:

1. **`scripts/parse_java_endpoints.py`** statically scans the Spring
   controllers (no compile, no running server, no Maven) and produces
   `app/catalog/endpoint_catalog.json` — every path, HTTP method, path/query
   param, and (where the DTO is a plain Lombok/getter-setter class)
   resolved request-body field schema, plus an equivalent OpenAPI 3.0 doc.
2. Every endpoint gets embedded into Chroma (**`app/rag/ingest.py`**).
3. For each user message, **`app/rag/retriever.py`** semantically retrieves
   only the ~12 most relevant endpoints.
4. **`app/agent/nodes.py`**'s planner (instructor + structured output) picks
   one and extracts arguments.
5. **`app/agent/executor.py`** is a single generic function that can call
   *any* catalog endpoint from its spec — there is no per-endpoint code
   anywhere in this system.

Run against your actual repo: **633 endpoints, 84 modules**, DELETE 48 /
GET 347 / PATCH 3 / POST 152 / PUT 83 — matching the raw annotation counts
exactly.

## Auth: same login as Xevyte Connect, nothing new

The agent never has, generates, or verifies a JWT. It mirrors
`employee-login-portal/src/auth/SSOHandler.js` exactly: redirect the user
to Scaloz IAM, receive `?scaloz_token=...` on the way back, use that token
as the Bearer token on every HRMS API call — precisely what the React
frontend does. Every call the agent makes carries the *user's own* session,
so the backend's existing `@PreAuthorize` checks and tenant scoping apply
exactly as if they'd clicked through the UI. The agent's guardrails
(below) are a UX layer on top of that, not a replacement for it.

**One thing to verify with whoever administers Scaloz IAM:** the current
`SSOHandler.js` redirects to `{iam}/Home` with no return-URL parameter —
IAM and the HRMS frontend apparently agree out-of-band on where to bounce
back (that config lives in the separate IAM/Scaloz Workspace service, not
in this repo). `app/auth/sso.py` optimistically appends a `redirect_to`
param pointing at the agent's own `/api/agent/auth/callback` (the
`SSOHandler.js` docstring names this as supported even though the current
code doesn't exercise it) — if IAM isn't configured to honor it yet, use
the manual fallback instead:

```bash
# after logging into the HRMS web app once, copy the token from
# sessionStorage (devtools → Application → Session Storage → scaloz_token)
curl -k -X POST https://localhost:8443/api/agent/auth/token \
    -H "Content-Type: application/json" \
    -d '{"token": "<paste it here>"}' -c cookies.txt
```

## Quick start

```bash
# 1. install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configure
cp .env.example .env
# fill in OPENAI_API_KEY, HRMS_API_BASE_URL, SESSION_SECRET_KEY (see comments in .env.example)

# 3. database
docker run -d --name xevyte-agent-pg -e POSTGRES_USER=xevyte_agent \
    -e POSTGRES_PASSWORD=xevyte_agent -e POSTGRES_DB=xevyte_agent -p 5432:5432 postgres:16-alpine
# (or point DATABASE_URL at any Postgres you already have — tables auto-create on startup)

# 4. generate the endpoint catalog from YOUR Java source
python scripts/parse_java_endpoints.py \
    --src /path/to/employee-login-backend2/src/main/java/com/register/example \
    --out app/catalog

# 5. embed it for RAG
python scripts/ingest_catalog.py

# 6. local HTTPS cert (dev only — see certs/generate_self_signed.sh header for prod)
./certs/generate_self_signed.sh
# then set SSL_KEYFILE=certs/key.pem / SSL_CERTFILE=certs/cert.pem in .env

# 7. run
python -m app.main
# → https://localhost:8443/docs for the agent's own Swagger UI
```

### Or with Docker

```bash
cp .env.example .env   # fill in the same values as above
docker compose up --build
```

## Using it

```bash
# start login (or use the manual /auth/token fallback above)
curl -k https://localhost:8443/api/agent/auth/login
# open the returned sso_redirect_url in a browser, log in, land back on /callback

# chat (reuse the session cookie the callback set)
curl -k -X POST https://localhost:8443/api/agent/chat -b cookies.txt \
    -H "Content-Type: application/json" \
    -d '{"message": "apply for 2 days of casual leave starting Monday"}'

# if the response has status "needs_confirmation", approve or decline:
curl -k -X POST https://localhost:8443/api/agent/confirm -b cookies.txt \
    -H "Content-Type: application/json" \
    -d '{"conversation_id": "...", "pending_confirmation_token": "...", "approve": true}'
```

## Guardrails

Every planned call gets a risk tier (`app/guardrails/risk.py`) before it's
allowed to execute:

| Tier | Examples | Behavior |
|---|---|---|
| LOW | plain GETs | executes immediately |
| MEDIUM | ordinary POST/PUT (apply leave, add asset category); GETs on sensitive modules | confirmation required *(default threshold)* |
| HIGH | DELETE; bulk actions; writes on sensitive modules | confirmation required |
| CRITICAL | payroll release/generate, role/access-control changes, permanent deletes | confirmation required |

Tune the threshold with `REQUIRE_CONFIRMATION_ABOVE_RISK` in `.env`. Every
executed call — confirmed or not — is written to `audit_log` with
PII-redacted request/response summaries (`app/guardrails/pii.py`).

This is policy, not the security boundary: the real boundary is the Xevyte
Connect backend itself, since every call carries the actual user's token.

## Re-run when the Java backend changes

**Automatically**, if the agent can see the Java source on disk (same host,
or a mounted volume — set `JAVA_SOURCE_DIR` + `AUTO_WATCH_JAVA_SOURCE=true`
in `.env`): the agent watches for `.java` changes and re-parses + re-embeds
a few seconds after edits go quiet. Verified live against the real repo —
adding one new `@GetMapping` to a controller took the catalog from 633 to
634 endpoints automatically, no script run, no restart.

**Or manually / from CI-CD**, if the agent runs somewhere without
filesystem access to the Java repo:

```bash
python scripts/parse_java_endpoints.py --src <path> --out app/catalog
curl -X POST https://localhost:8443/api/agent/catalog/refresh -b cookies.txt
```

or in one call (agent-side, needs the source reachable from wherever the
agent runs — e.g. checked out by the same CI job just before this call):

```bash
curl -X POST https://localhost:8443/api/agent/catalog/refresh-from-source \
    -b cookies.txt -H "Content-Type: application/json" \
    -d '{"java_source_dir": "/path/to/.../com/register/example"}'
```

**Worth doing regardless:** add `springdoc-openapi-starter-webmvc-ui` to
`employee-login-backend2/pom.xml`. There's already a `springdoc.*` config
block sitting inert in `application.yml` (the dependency was never added).
One Maven dependency gets you a live `/v3/api-docs` reflecting Spring's
actual routing table — `app/catalog/loader.py` could then optionally
pull from that instead of/alongside static parsing for endpoints where
reflection catches something regex can't (e.g. validation annotations).
Static parsing works fine today and needs no backend changes, so this is
an enhancement, not a blocker.

## Evals

```bash
python -m pytest evals/test_retrieval.py -v   # deterministic recall@12, needs only an embedding call
python -m pytest evals/test_planner.py -v     # GEval-judged planning quality, needs OPENAI_API_KEY
```

`evals/golden_queries.json` has 15 hand-written natural-language queries
mapped to real endpoint ids sampled across Leave, Payroll, Assets,
Tickets, Grievance, Travel, Insurance, Employee, Project, Profile,
Notifications, and Claims — add more as you find gaps.

## Known limitations

- **Bulk array-body endpoints** (e.g. `POST /api/assets/categories` taking
  `List<AssetCategoryDTO>`) — the planner's structured-output schema
  represents `body` as a single flexible field to stay generic across all
  633 endpoints; array bodies work but get less strict validation than
  object bodies. Fine in practice, called out here so it's not a surprise.
- **53 of 149 body-taking endpoints** resolve to a raw `Map<String,Object>`
  in the Java source itself (not a parser gap — genuinely no static DTO to
  reflect), so the LLM infers field names from the description/conversation
  for those instead of a strict schema. `endpoint_catalog.json` ->
  `request_body_schema: null` marks exactly which ones.
- File-upload chat turns (leave attachments, bulk Excel imports, etc.) are
  supported in `executor.py`/`nodes.py` at the plumbing level but the
  `/api/agent/chat` route as shipped is JSON-only — wire a
  multipart-accepting variant if you need this from chat directly.
- The SSO `redirect_to` caveat above.

## Project layout

```
app/
  agent/       state machine (LangGraph), planner (instructor), generic executor, prompts
  auth/        Scaloz IAM SSO mirroring + encrypted session storage
  catalog/     endpoint_catalog.json (generated) + loader
  guardrails/  risk tiering, PII redaction, prompt-injection/cross-identity checks
  rag/         Chroma ingestion + retrieval (LiteLLM-backed embeddings)
  routers/     FastAPI routes (auth, chat, catalog admin)
  main.py      FastAPI app
scripts/
  parse_java_endpoints.py   the auto-discovery parser — re-run any time the Java changes
  ingest_catalog.py         re-embed the catalog into Chroma
evals/          deepeval + pytest suites
sql/init_db.sql Postgres schema (also auto-created on startup)
```

## Stack

FastAPI · Uvicorn · LangGraph · LangChain · langchain-openai · instructor ·
LiteLLM · LangSmith · Tenacity · ChromaDB · pypdf · tiktoken · PostgreSQL ·
SQLAlchemy · Pydantic · httpx · python-multipart · python-dotenv ·
deepeval · OpenAPI/Swagger (native FastAPI docs + the generated HRMS
catalog spec)
