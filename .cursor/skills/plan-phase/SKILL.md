---
name: plan-phase
description: >-
  Writes a phase implementation plan before any code. Use when the user asks to
  plan a phase, design the next slice, or start SDLC planning for ClaimsAI
  Sentinel. Does not implement.
---

# Plan a phase

Write the plan. Do not change application code, SQL, or tests.

## Read first

1. `docs/implementation-phases.md` — the phase and its **Done when**.
2. The component section in `docs/consolidated-design.md`, then that component's design doc if the phase names one.
3. The previous plan in `.cursor/plans/` so the new plan starts where the last one stopped.
4. The code the phase will touch, only enough to name real files.

## Rules for the plan

- One phase. Do not pull in the next phase or payment, letters, or notifications.
- State who writes which schema. Claim rows stay with the payer service.
- If a model is involved, say what it proposes and what code accepts. Name the agent result fields when the adjudicator will route on them: `verdict`, `confidence`, `reasons`, `evidence`, `error`.
- Reuse ports 47110 portal, 47111 payer, 47112 chatbot, 47117 Vite. A new service gets the next port and its own schema.
- Schema changes on a database that already runs are a new `db/sql/00N_*.sql`, not an edit that drops schemas.

## Write

Create `.cursor/plans/phase_N_<slug>.plan.md`:

```markdown
---
name: Phase N short title
overview: One sentence. Who writes what.
todos:
  - id: kebab-id
    content: One deliverable
    status: pending
isProject: false
---

# Phase N — title

Done when: <copy from implementation-phases.md>

Out of scope: <the next phase and anything the design defers>

## Behavior
<What changes for the user or the next service. Link the files that exist today.>

## Checks
<The cases that prove Done when. Name the fixture or status.>
```

Keep todos to the work inside this phase. Each todo is something that can be finished and checked on its own.

Stop after the plan. Ask the user to confirm before implementation.
