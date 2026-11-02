from chatbot.nodes.propose import parse_value
from chatbot.tools.payer import detail_of, post_answer


def coerce_value(field_path: str, value):
    name = field_path.rsplit(".", 1)[-1]
    if name == "units":
        return int(value)
    if name == "diagnosis_pointers":
        if isinstance(value, list):
            return [int(item) for item in value]
        return [int(part.strip()) for part in str(value).split(",") if part.strip()]
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return value


def act_node(state: dict) -> dict:
    proposal = state.get("proposal") or {}
    say = str(proposal.get("say") or "").strip()
    action = proposal.get("action")
    issue_id = proposal.get("issue_id")
    open_issues = state.get("open_issues") or []
    open_by_id = {int(issue["issue_id"]): issue for issue in open_issues}
    user_text = (state.get("user_text") or "").strip()
    if action != "submit" or not user_text or issue_id is None or int(issue_id) not in open_by_id:
        return {"reply": say, "submitted": False}
    issue = open_by_id[int(issue_id)]
    value = parse_value(proposal.get("value_json"))
    if value is None:
        return {"reply": say, "submitted": False}
    try:
        value = coerce_value(issue["field_path"], value)
    except (TypeError, ValueError):
        return {"reply": say, "submitted": False}
    status, body = post_answer(
        state["claim_id"],
        int(issue_id),
        value,
        state["conversation_id"],
        user_text,
        state["submitter_id"],
        state["actor"],
    )
    if status == 422:
        detail = detail_of(body)
        reply = say if detail and detail in say else f"{say} {detail}".strip()
        return {"reply": reply, "submitted": False}
    if status != 200:
        detail = detail_of(body) or "The payer service could not accept that answer."
        reply = say if detail in say else f"{say} {detail}".strip()
        return {"reply": reply, "submitted": False}
    return {
        "reply": say,
        "submitted": True,
        "claim_status": body.get("claim_status") or state.get("claim_status"),
    }
