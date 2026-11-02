---
name: verify-phase
description: >-
  Checks a ClaimsAI Sentinel change against the phase Done when. Use when the
  user asks to verify, test, or check a phase, or before calling a phase done.
---

# Verify a phase

Prove the plan's **Done when**. Do not add features while verifying.

## Which checks

| Change | Run |
|---|---|
| Payer rules, intake, portal API | `src/backend/.venv/bin/pytest src/backend/tests/test_rules.py src/backend/tests/test_block_a.py -q` from the repo root |
| Chatbot | `src/backend/.venv/bin/pytest src/backend/tests/test_chatbot.py -q` — needs network and `OPENAI_API_KEY` |
| Any Python behavior | The closest test file under `src/backend/tests/`. Add a test only when the plan's Checks section has no cover. |
| React page, route, or client state | Exercise the flow in the browser (click, type, submit). A screenshot is not enough. Walk the other page that reads the same state. |

From the repo root, pytest must see `src/backend` on `PYTHONPATH`. If the invocation cannot import `portal` or `payer_service`, rerun with `PYTHONPATH=src/backend`.

## Report

```markdown
## Done when
- [ ] <criterion> — pass/fail and the command or click path

## Skipped
- <check> — why (missing key, server down)

## Still open
- <what would have to be true to mark the phase done>
```

A skipped check is not a pass. Do not say the phase is done while a **Done when** line is open.
