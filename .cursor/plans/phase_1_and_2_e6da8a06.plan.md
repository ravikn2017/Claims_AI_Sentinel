---
name: Phase 1 and 2
overview: Use the PostgreSQL 18 server you already open in Postico, install only RabbitMQ, and add pgvector to that existing server. Then stand up the empty apps and create every table.
todos:
  - id: install-servers
    content: Install and start RabbitMQ with Homebrew, and add the pgvector extension to the existing PostgreSQL 18 server
    status: completed
  - id: app-shells
    content: Create the full repo tree under src/frontend and src/backend, plus empty .cursor folders and Agents.md. Fill only the portal, payer service, and React health shells.
    status: completed
  - id: rabbit-topology
    content: Declare the claims exchanges, payer queue, retry queues, and DLQ
    status: completed
  - id: ddl
    content: Add SQL for the four schemas, all tables, the audit view, roles, and append-only triggers
    status: completed
  - id: verify
    content: Apply SQL on a fresh database and confirm health, topology, and the append-only guard
    status: completed
isProject: false
---

# Phase 1 and 2 — local platform and database

You do need RabbitMQ. It is not installed. Postgres is already there: PostgreSQL 18 under `/Library/PostgreSQL/18`, which is the server Postico connects to. Do not install a second Postgres. Python 3.14 and Node 24 are already installed. Docker is not needed.

Install and start only RabbitMQ:

```bash
brew install rabbitmq
brew services start rabbitmq
rabbitmq-plugins enable rabbitmq_management
```

The management UI is at `http://localhost:15672` (local `guest` / `guest`). The apps use `amqp://guest:guest@localhost:5672/`.

pgvector is not in this Postgres yet (no `vector` extension under `/Library/PostgreSQL/18`). Phase 2 builds pgvector against `/Library/PostgreSQL/18/bin/pg_config` and installs the extension files into that server. That step needs your macOS password because the server files are outside the home folder.

You create the empty database yourself in Postico, before implementation starts. Name it `claimsai` on the connection you already use, and put that host, port, user, and password in `.env`. The generated code does not run `CREATE DATABASE`. `db/apply.sh` only creates the schemas, tables, roles, and view inside `claimsai`. Other databases on that server stay untouched.

Phase 1 declares the broker topology. Phase 4 is the first time a claim message is published. Nothing in Phase 2 talks to the queue.

## Folder structure

Phase 1 creates this whole tree. Later-phase files are empty placeholders (`.gitkeep` or empty `__init__.py`) so the folders stay in git. Phase 1 fills only the platform pieces called out below.

`Agents.md`, `.cursor/mcp.json`, and the files under `.cursor/rules`, `.cursor/skills`, `.cursor/agents`, and `.cursor/commands` stay empty. `.cursor/plans` already exists and is left as it is. `.cursor/agents` is for Cursor agent definitions. The LangGraph agents live under `src/backend`.

```text
Agents.md
.env.example
.gitignore
.cursor/
  mcp.json
  plans/                         # already present
  rules/
  skills/
  agents/
  commands/
docs/                            # already present
data/documents/                  # local files, gitignored
infra/
  rabbitmq_topology.py           # Phase 1
db/
  apply.sh                       # Phase 2
  sql/                           # Phase 2
src/
  frontend/                      # Vite + React
    package.json
    index.html
    src/
      main.tsx
      App.tsx                    # Phase 1 health page
      pages/
        submit/                  # Phase 4
        status/                  # Phase 4
        chat/                    # Phase 7
        review/                  # Phase 13
  backend/
    requirements.txt             # Phase 1: FastAPI, SQLAlchemy, Pydantic, aio-pika
    portal/                      # Phase 1 health, Phase 4 intake
      app/main.py
    payer_service/               # Phase 1 health, Phase 5 claim pipeline
      app/main.py
    chatbot/                     # Phase 7
    adjudicator/                 # Phase 9 orchestrator
    policy_compliance/           # Phase 10
    fraud_detection/             # Phase 11
    medical_necessity/           # Phase 12
```

Each of `chatbot`, `adjudicator`, `policy_compliance`, `fraud_detection`, and `medical_necessity` uses the same layout as the BasicChatbot project (`graph`, `LLMS`, `nodes`, `state`, `tools`, plus `app.py`). The Streamlit `ui` folder from that project is not copied. Screens stay in `src/frontend`.

```text
src/backend/adjudicator/
  app.py
  graph/
    __init__.py
    graph_builder.py             # StateGraph, like GraphBuilder.setup_graph
  LLMS/
    __init__.py
  nodes/
    __init__.py                  # load, route, investigation, review, decide
  state/
    __init__.py
    state.py                     # TypedDict state for the run
  tools/
    __init__.py                  # payer-service HTTP calls
```

`policy_compliance`, `fraud_detection`, `medical_necessity`, and `chatbot` get the same five folders. Their `nodes` and `tools` stay empty until that agent's phase. The orchestrator calls those packages from its own nodes. It does not grow a `ui` package.

## Phase 1 — empty platform that can see itself

What Phase 1 actually implements inside that tree:

- `infra/rabbitmq_topology.py` — durable topology from [docs/payer-service-design.md](docs/payer-service-design.md): topic exchange `claims.events`, quorum queue `payer.claim_submitted` (delivery limit 5, dead-letter to `claims.dlx`), direct exchange `claims.retry`, delay queues `payer.claim_submitted.retry.10s` and `.retry.60s` (TTL then back to `payer.claim_submitted`), and quorum queue `payer.claim_submitted.dlq` with no consumer. Quorum queues are fine on one local node.
- `src/backend/portal/app/main.py` — FastAPI, `GET /health`, checks Postgres and RabbitMQ. Port 8000.
- `src/backend/payer_service/app/main.py` — same health check. Port 8001.
- `src/frontend` — one page that calls the portal health endpoint and shows database and queue status.
- `.env.example` — `DATABASE_URL`, `RABBITMQ_URL`, document folder path. Real `.env` stays untracked.
- One Python venv for `src/backend` on the Python already installed (3.14). A second Python is installed only if a package refuses 3.14.

Both health endpoints must fail if either Postgres or RabbitMQ is down, so "they can see each other" is a real check.

**Done when:** RabbitMQ is up, the topology script has created the exchanges and queues (visible in the management UI), both `/health` calls reach the existing Postgres and the queue, and the React page shows that status.

## Phase 2 — all tables, still empty

`claimsai` already exists because you created it in Postico. It starts empty. `db/apply.sh` then creates four schemas inside it: `portal`, `claims`, `adjudication`, `fraud`. SQL files live under `db/sql/` and are applied with `/Library/PostgreSQL/18/bin/psql` using the Postico connection settings. The same script can be opened and run in Postico. Re-running it on a fresh `claimsai` recreates the schema. pgvector is `CREATE EXTENSION vector` after the extension files are installed into this server.

Roles, matching the payer service design: `claims_owner` runs migrations, `payer_app` is what the payer service connects as. `payer_app` gets `SELECT, INSERT` only on `claim_status_history`, `claim_amendment`, `document_extraction`, and `audit_event`. A `BEFORE UPDATE OR DELETE` trigger on those four tables raises an error. A trigger on `claim` rejects any change to `source_message`. Skip the hash-chain columns (design section 12.6).

Tables follow [docs/consolidated-design.md](docs/consolidated-design.md) section 7.2 and the column notes in the component docs:

- `portal.submission_log`
- `claims` reference: `member`, `policy`, `provider` (including `quality_rating`, `city`, `state`), `plan_benefit`, `ref_cpt`, `ref_icd10`
- `claims` claim data: `claim` (nullable relational columns until `VALIDATED`, plus the `CHECK` from the payer service design, `draft`, `source_message`, `reference_snapshot`), `claim_line` (including nullable `prior_auth_number`), `claim_document`, `claim_issue`, `claim_amendment`, `document_extraction`, `claim_status_history`
- `claims` plumbing: `outbox` (partial index where `published_at` is null), `intake_error`, `audit_event`
- `claims.claim_audit_trail` view: one row shape (`claim_id`, `occurred_at`, `source`, `summary`) unioning status history, amendments, issues, extractions, outbox, and audit events
- `adjudication.payer_doc_chunk` with `embedding vector(768)` — empty until Phase 8; dimension can change before any rows exist
- `adjudication.review_tasks` with `task_type` `REVIEW` or `INVESTIGATION`
- `adjudication.adjudication_event`
- `fraud`: the eight tables in [docs/fraud-detection-agent-design.md](docs/fraud-detection-agent-design.md) section 9. `provider_stats` stores the nightly feature set as `features jsonb` plus `provider_risk`, so the Kaggle feature list is not frozen in columns now

Same-database foreign keys where a row cannot exist first: `claim.submission_id` → `portal.submission_log`, claim lines, documents, issues, amendments, and status history → `claim`. `document_extraction` has no foreign key to `claim_document`, because extraction is saved before the claim transaction. Agent tables store `claim_id` without a foreign key into `claims`, so those schemas stay writable by their own owners later.

LangGraph checkpoint tables are not hand-written. The library creates them in `adjudication` when the orchestrator starts in Phase 9.

No seed rows in this phase.

**Done when:** `db/apply.sh` on an empty database creates every table and the view, the append-only trigger rejects an update, and both health checks still pass.
