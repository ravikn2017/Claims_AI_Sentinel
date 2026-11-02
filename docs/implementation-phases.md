# ClaimsAI Sentinel — Implementation phases

High-level build order. This is the sequence to follow, not the detailed plan.
After this is agreed, each phase gets its own implementation plan.

Design source: `consolidated-design.md` and the component docs.
Scope ends at `APPROVED` or `DENIED` plus `AdjudicationDecided`. Payment, member letters, and notifications come later.

## Stack

| Layer | Choice |
|---|---|
| Frontend | React — payer portal, and later the reviewer / investigator screens |
| Backend | Python, FastAPI — one service per component |
| Database | One local Postgres instance |
| Vector store | **pgvector in that same Postgres** — no separate vector database |
| Queue | RabbitMQ |
| Orchestration | LangGraph, checkpoints stored in Postgres |
| Documents | Local folder. Messages store a path and a hash, never the file bytes |

Postgres has one schema per owner: `portal`, `claims`, `adjudication`, `fraud`.
The pgvector extension is enabled on the instance. Embeddings live in `adjudication.payer_doc_chunk`, shared by policy compliance (plan documents) and medical necessity (medical policies).

Two blocks. Finish and check Block A before starting Block B.

---

## Block A — Portal, payer service, and the database

Everything a claim needs to be accepted, checked, and stored. No adjudication agents yet.

### Phase 1. Local platform

Stand up the empty system so later phases only add behavior.

1. Postgres with the pgvector extension, plus the four schemas.
2. RabbitMQ, with the exchanges and queues from the payer service design (`claims.events`, the payer queue, retry queues, dead-letter queue).
3. A local document folder.
4. Python project layout for the portal API and the payer service (FastAPI, SQLAlchemy, Pydantic).
5. A React app shell for the portal.

**Done when:** the database, the queue, and both apps start locally and can see each other.

### Phase 2. All tables

Create every table from section 7 of the consolidated design, including tables the agents will use later. Empty tables are fine.

1. `portal`: `submission_log`.
2. `claims`: reference data (`member`, `policy`, `provider`, `plan_benefit`, `ref_cpt`, `ref_icd10`) and claim data (`claim`, `claim_line`, `claim_document`, `claim_issue`, `claim_amendment`, `document_extraction`, `claim_status_history`, `outbox`, `intake_error`, `audit_event`).
3. `adjudication`: `payer_doc_chunk` (with a pgvector embedding column), `review_tasks`, `adjudication_event`, and room for the LangGraph checkpoint tables.
4. `fraud`: assessment, stats, labels, memos, and the assistant log.
5. The `claim_audit_trail` view.

`review_tasks` includes a task type so human review and investigation share one queue.

**Done when:** the schema matches the design and a fresh database can be created from scratch.

### Phase 3. Seed data for intake

A small synthetic world, enough to submit and validate claims. Planted fraud schemes and medical-policy cases wait until Block B.

1. A few members, two plans, providers, CPT and ICD-10 codes, and plan benefits.
2. A handful of claim payloads: one clean claim, one with a fixable error, one that should be rejected.

**Done when:** the validation rules have reference rows to read.

### Phase 4. Payer portal

Intake only. The portal checks shape, stores files, and publishes one message. It does not validate the business of the claim.

1. FastAPI intake: accept a professional claim, check the JSON shape, file type, and file size, and reject a duplicate `submission_id`.
2. Save documents to the local folder. The message carries `storage_uri` and `sha256`.
3. Write `submission_log` and publish `claim.submitted` through the outbox.
4. React screens: submit a claim, upload a document, track status (status is read from the payer service).
5. After the portal path works: a folder drop for email/PDF and a partner API endpoint, both producing the same message.

**Done when:** a submission from the React form creates one log row and one `claim.submitted` message, and a repeat of the same id is rejected.

### Phase 5. Payer service

The only writer of the claims database. Turns a queue message into a claim.

1. Consume `claim.submitted`. Ack only after the database commit. Retries, then the dead-letter queue.
2. If the submission is a document, extract a draft (evidence required for each field). If the portal already sent a claim, store the documents and skip extraction.
3. Run the business rules. Write the claim, lines, documents, issues, history, and the outbox event in one transaction.
4. Outcomes: `VALIDATED` and `claim.ready_for_adjudication`, or `PENDING_INFO` and `claim.info_requested`, or `REJECTED` and `claim.rejected`.
5. HTTP API the rest of the system needs: claim status, open issues, answers to issues, status transitions, and an audit row on every read.
6. Sweeper for `PENDING_INFO` claims that pass their reply deadline. Small scripts to inspect and replay the dead-letter queue.

The chatbot conversation itself is Block B. This phase only builds the APIs it will call.

**Done when:** the three seed claims end as validated, pending info, or rejected, and the portal status page shows that result.

### Phase 6. Check Block A end to end

One path, no agents.

1. Submit from the React portal.
2. Message lands on the queue.
3. Payer service writes the claim.
4. Portal shows the status and, for a pending claim, the open issues.
5. An answer through the issues API revalidates the claim.

**Stop here and review** before building agents.

---

## Block B — Agents, then wiring

Each agent is built and checked on its own. Wiring means plugging it into the adjudicator graph, not rewriting it.

### Phase 7. Missing-info chatbot

Closes the intake loop using the APIs from Phase 5.

1. A React chat panel on the portal.
2. The bot reads open issues, asks in plain language, and posts the claimant's answer.
3. The payer service still decides whether the answer is valid. The bot never writes the claim.

**Done when:** a `PENDING_INFO` claim can be corrected in the chat and move to `VALIDATED`.

### Phase 8. Document index (pgvector)

Shared reading material for the two agents that use retrieval.

1. Load the synthetic plan documents and medical policies into `payer_doc_chunk`.
2. Store embeddings in the pgvector column.
3. A small search function: given a plan or a procedure code, return the relevant chunks.

**Done when:** a query for a known policy section returns that section from Postgres.

### Phase 9. Adjudicator skeleton

The graph and the routing, with stand-in agents. This is the wiring harness.

1. Consume `claim.ready_for_adjudication`. One run per claim attempt. Idempotent on that attempt.
2. Load the claim from the payer service and move it to `IN_ADJUDICATION` through the transitions API.
3. LangGraph: parallel policy and fraud branches, the join rules, medical necessity, investigation pause, human-review pause, then decide.
4. Stand-in agents return the shared result (`verdict`, `confidence`, `reasons`, `evidence`, `error`) so the routes can be tested without models.
5. Checkpoints in Postgres. Pauses do not hold a worker.
6. On a decision, ask the payer service to set `APPROVED` or `DENIED`, and emit `AdjudicationDecided`.

**Done when:** a validated claim walks the graph with stand-in results and finishes in the status the routing table says it should.

### Phase 10. Policy compliance agent

"Is this line covered?"

1. Deterministic checks against `plan_benefit`, the policy dates, and network status.
2. Retrieval over the plan-document chunks in pgvector for exclusions and exceptions.
3. The model may explain and cite. Code checks the citation against the benefit table before the verdict is kept.
4. Plug the real agent into the skeleton in place of the policy stand-in.

**Done when:** a covered line and a not-covered line each get the verdict the seed plan says they should.

### Phase 11. Fraud detection agent

"Is this claim genuine?"

1. The fraud schema filled from the synthetic claims (and the provider-level dataset where the design uses it).
2. Hard rules plus the score. The score and the rules set the verdict; the model writes the narrative.
3. Persist the assessment. Plug the agent into the fraud branch of the graph.

**Done when:** a clean claim is clear and a planted suspicious claim is flagged, and the graph routes each one correctly.

### Phase 12. Medical necessity agent

"Do the notes support this service?" Runs only after a line is covered.

1. Retrieval over the medical-policy chunks in the same pgvector table.
2. The model judges each criterion and must quote the note. Code drops a quote that is not actually in the note.
3. Low-quality provider flag from the provider columns, for the reviewer.
4. Plug the agent in after the policy branch.

**Done when:** a necessary and an unnecessary planted case each reach human review with the matching recommendation, and a failure does not auto-deny.

### Phase 13. Human review and investigation

The screens for the pauses the graph already has.

1. React queue: open tasks, sorted by risk, shared by review and investigation.
2. Atomic pick-up, 30-minute lease, only the assignee can decide.
3. Decision and investigation callbacks resume the LangGraph run.

**Done when:** two reviewers cannot take the same task, a decision resumes the graph, and the claim reaches `APPROVED` or `DENIED`.

### Phase 14. One claim, whole path

The golden path across both blocks.

1. Submit in the portal.
2. Payer service validates.
3. Policy and fraud run together.
4. Medical necessity runs when the line is covered.
5. A reviewer decides.
6. The portal shows the final status, and `AdjudicationDecided` has been emitted.

**Done when:** that path works for a clean claim, a not-covered claim, a fraud-flagged claim, and a claim that needed more information.

---

## Left for a later session

- Payment, member letters, and notifications that consume `AdjudicationDecided`.
- The fuller synthetic generator (planted schemes for every agent test table) can grow during Phases 10–12; it is not a separate product.
