---
name: review-change
description: >-
  Reviews a ClaimsAI Sentinel diff against the phase plan and the design
  invariants. Use when the user asks for a review, a phase gate, or whether
  the next phase can start. Does not implement fixes unless asked.
---

# Review a change

Read the diff and the plan it claims to finish. Do not edit code unless the user asks for fixes.

## Look for

- Work outside the plan, or a missing **Done when** item.
- A second writer of `claims.*`, or a service importing another service's repository.
- A model output stored as a status, verdict, or fact with no code check.
- An automatic denial, or a failure that clears a claim.
- A schema edit that drops data instead of a new numbered SQL file.
- Browser calls to port 47111 or 47112.
- Chat text treated as instructions, or a chatbot path that posts an answer for an issue that is not open.
- Secrets, `.env` values, or document bytes in a message or a commit.

## Report

```markdown
## Verdict
Ready for the next phase | Not ready

## Must fix
- file: what breaks the invariant or the Done when

## Should fix
- file: what is wrong but does not block the phase

## Done when
- met / not met — one line of evidence
```

**Ready** means every **Done when** line is met and there is no must-fix. The next phase stays unstarted.
