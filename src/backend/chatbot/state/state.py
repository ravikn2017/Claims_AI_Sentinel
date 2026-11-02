from typing import TypedDict


class ChatState(TypedDict, total=False):
    claim_id: str
    submitter_id: str
    conversation_id: str
    actor: dict
    user_text: str | None
    history: list[dict]
    open_issues: list[dict]
    claim_status: str
    proposal: dict
    reply: str
    submitted: bool
