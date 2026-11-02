---
name: model-cost
description: >-
  Chooses a Cursor model for cost and prints real usage from the team Admin
  API. Use when the user asks what a chat or the team cost, which model to
  use, spend, usage, or a daily cost report, or when spawning a subagent.
---

# Model cost

The chat model is the one the user selected. Change a model only when launching a subagent. Do not invent prices. Dollars come from the report script.

## Which model

Cursor's own models, Composer and Grok, are not charged the extra Cursor token fee. Third-party models can be. Use the cheapest model that can finish the step.

| Work | Model |
|---|---|
| Search, logs, a single todo with a written plan | `composer-2.5-fast` |
| Implement or verify | `composer-2.5` |
| Plan or review | `grok-4.7-high-fast` |
| The cheaper model already failed, or the user named a model | That model |

Do not launch several subagents on Opus, Fable, or other thinking-high models. One planner or one reviewer is enough.

## Report

Run from the repo root. The key is a team Admin API key from the Cursor dashboard. It is not an app secret. Do not write it into a file or the chat.

```bash
export CURSOR_ADMIN_API_KEY=...
export CURSOR_USER_EMAIL=you@example.com
python3 .cursor/skills/model-cost/scripts/usage_report.py
python3 .cursor/skills/model-cost/scripts/usage_report.py --scope team --days 7
```

`--scope me` is the signed-in person (`CURSOR_USER_EMAIL` or `--email`). `--scope team` is one row per member per day, for a team lead. The window max is 30 days. Members with no events are omitted. Sums use `chargedCents`, which is what reconciles with the billing dashboard.

If the key is missing or the API returns 401, say so and stop. Do not guess a dollar amount.
