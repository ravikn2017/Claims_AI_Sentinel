from chatbot.errors import ChatError
from chatbot.store import list_messages
from chatbot.tools.payer import detail_of, get_claim, get_open_issues


def load_node(state: dict) -> dict:
    claim_id = state["claim_id"]
    actor = state["actor"]
    status, claim = get_claim(claim_id, actor)
    if status == 404:
        raise ChatError(404, "Claim not found")
    if status != 200:
        raise ChatError(503, detail_of(claim) or "Payer service is unavailable")
    if claim.get("submitter_id") != state["submitter_id"]:
        raise ChatError(403, "This conversation does not belong to the claim's submitter")
    issue_status, issues = get_open_issues(claim_id, actor)
    if issue_status != 200:
        raise ChatError(503, "Payer service is unavailable")
    return {
        "open_issues": issues,
        "claim_status": claim.get("status") or "",
        "history": list_messages(claim_id),
    }
