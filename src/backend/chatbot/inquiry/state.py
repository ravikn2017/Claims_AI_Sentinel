from typing import TypedDict


class InquiryState(TypedDict, total=False):
    member_id: str
    actor: dict
    user_text: str
    history: list[dict]
    lookup: dict
    facts: dict
    reply: str
