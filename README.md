# ClaimsAI Sentinel

Local learning build for synthetic US professional claims (CPT, ICD-10, NPI). A claim can be submitted, checked, and adjudicated through **APPROVED** or **DENIED**. Payment, member letters, and notifications are out of scope.

Design: [`docs/consolidated-design.md`](docs/consolidated-design.md). Build order: [`docs/implementation-phases.md`](docs/implementation-phases.md).

## How it fits together

The browser talks only to the portal. The payer service is the only writer of `claims.*`. An LLM output is not a status or a stored fact until deterministic code checks it. A failure never auto-denies or auto-clears a claim.

| Service | Port | Writes |
|---|---|---|
| Portal (FastAPI) | 47110 | `portal` |
| Payer service | 47111 | `claims` |
| Chatbot | 47112 | `chatbot` |
| Adjudicator | 47113 | `adjudication` |
| React portal (Vite) | 47117 | — |

Postgres is one local instance with pgvector. RabbitMQ carries claim events. Each service writes only its own schema.

## Run locally

Needs local Postgres (with pgvector), RabbitMQ, Python 3, and Node.

```sh
cp .env.example .env
python3 -m venv src/backend/.venv
src/backend/.venv/bin/pip install -r src/backend/requirements.txt
./db/apply.sh
src/backend/.venv/bin/python db/seed.py
src/backend/.venv/bin/python infra/rabbitmq_topology.py
```

`db/apply.sh` applies `db/sql/001_schema.sql` through `003_app_user.sql`. Apply `004_chatbot.sql`, `005_inquiry.sql`, and `006_adjudicator.sql` the same way when those services are in use. The script calls Postgres 18 at `/Library/PostgreSQL/18/bin/psql`.

Seeded demo logins use password `sentinel`:

| Email | Role |
|---|---|
| provider@example.test | provider |
| member@example.test | member |
| reviewer@example.test | reviewer |
| investigator@example.test | investigator |
| ops@example.test | ops |

Start each process from `src/backend` (the portal UI from `src/frontend`):

```sh
cd src/backend
.venv/bin/python -m portal.app.main
.venv/bin/python -m payer_service.app.main
.venv/bin/python -m chatbot.app
.venv/bin/python -m adjudicator.app
```

```sh
cd src/frontend
npm install
npm run dev
```

Open the portal at http://127.0.0.1:47117. Tests run from `src/backend` with `.venv/bin/pytest`.

## What stays local

`.env` is not committed. Copy `.env.example` and fill in keys you use (Langfuse, model access). PDF, Word, CSV, and Pages files are ignored.
