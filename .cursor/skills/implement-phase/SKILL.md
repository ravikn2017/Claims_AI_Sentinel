---
name: implement-phase
description: >-
  Implements one agreed ClaimsAI Sentinel phase plan, one todo at a time. Use
  when the user says to build, implement, or continue a phase that already has
  a plan. Do not start the next phase.
---

# Implement a phase

## Start

1. Read the plan in `.cursor/plans/` the user named. If none is named, use the latest plan whose todos are not all completed.
2. If that plan was not confirmed in this conversation, stop and ask before editing code.
3. Read `.cursor/rules/` files that match the files you will touch.

## Build

- Finish one todo, then mark it `completed` in the plan. Do not start a later todo that depends on a failing one.
- Stay inside the plan. A new table, queue, port, or screen needs a plan change first.
- Match the neighboring module. Portal shape checks stay in the portal. Business rules and `claims.*` writes stay in the payer service. Agents call the payer over HTTP.
- A model call returns a proposal. The next function decides whether to keep it.
- Do not commit unless the user asks.

## Stop

Stop when the plan's todos are done, or when a check fails and the next todo would hide it. Report what changed, how it was checked, and which **Done when** items are still open. Do not begin the next phase in `docs/implementation-phases.md`.
