import logging

from langchain_core.runnables import RunnableConfig

from chatbot.nodes.propose import ask_model
from chatbot.tools.payer import get_claim, get_open_issues

log = logging.getLogger("chatbot.followup")


def _closing(status: str) -> str:
    if status == "VALIDATED":
        return "The claim is complete and queued for adjudication."
    if status == "REJECTED":
        return "The claim was rejected. Submit it again as a new claim."
    return f"The claim is now {status}."


def followup_node(state: dict, config: RunnableConfig) -> dict:
    claim_id = state["claim_id"]
    actor = state["actor"]
    status, claim = get_claim(claim_id, actor)
    claim_status = claim.get("status") if status == 200 else state.get("claim_status") or ""
    issue_status, issues = get_open_issues(claim_id, actor)
    if issue_status != 200:
        issues = []
    reply = (state.get("reply") or "").strip()
    if not issues:
        extra = _closing(claim_status)
        return {"reply": f"{reply} {extra}".strip(), "open_issues": [], "claim_status": claim_status}
    follow = {
        **state,
        "open_issues": issues,
        "claim_status": claim_status,
        "user_text": None,
    }
    try:
        proposal = ask_model(follow, config)
        extra = proposal.say
    except Exception:
        log.warning("follow-up question failed claim_id=%s", claim_id)
        extra = issues[0]["message"]
    return {"reply": f"{reply} {extra}".strip(), "open_issues": issues, "claim_status": claim_status}
