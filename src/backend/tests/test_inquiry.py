"""Member inquiry. The model is stubbed; the payer reads use the database."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from chatbot.db import chatbot_engine
from chatbot.errors import ChatError
from chatbot.inquiry.nodes import Lookup, facts_for
from chatbot.inquiry.service import post_inquiry
from payer_service.app.db import payer_engine
from payer_service.app.repository import read_member_claims, read_member_coverage, search_providers

ACTOR = {
    "actor_type": "user",
    "actor_id": "MBR-100231",
    "actor_role": "member",
    "correlation_id": "inquiry-test",
}
MEMBER = "MBR-TEST-INQUIRY"


def _clear(member_id: str) -> None:
    with chatbot_engine().begin() as conn:
        conn.execute(text("DELETE FROM chatbot.inquiry_message WHERE member_id = :member_id"), {"member_id": member_id})
        conn.execute(
            text("DELETE FROM chatbot.inquiry_conversation WHERE member_id = :member_id"),
            {"member_id": member_id},
        )


def test_member_claims_and_coverage_stay_on_that_member():
    with payer_engine().begin() as conn:
        claims = read_member_claims(conn, "MBR-100231", ACTOR)
        coverage = read_member_coverage(conn, "MBR-100231", ACTOR)
        other = conn.execute(
            text(
                """
                SELECT claim_id FROM claims.claim
                WHERE member_id IS DISTINCT FROM 'MBR-100231'
                  AND submitter_id IS DISTINCT FROM 'MBR-100231'
                LIMIT 1
                """
            )
        ).scalar()
    assert claims is not None and coverage is not None
    assert "quality_rating" not in json.dumps(claims)
    assert {row["plan_code"] for row in coverage["policies"]} == {"SILVER-PPO-01"}
    if other:
        assert other not in {row["claim_id"] for row in claims["claims"]}


def test_provider_search_omits_quality():
    with payer_engine().begin() as conn:
        rows = search_providers(conn, "Lakeside", ACTOR)
    assert rows
    assert rows[0]["name"] == "Lakeside Family Clinic"
    assert "quality_rating" not in rows[0]
    assert set(rows[0]) == {"provider_id", "npi", "name", "network_status", "city", "state"}


def test_policy_question_reads_coverage_even_if_the_model_picks_claims(monkeypatch):
    called = {}

    def coverage(member_id, actor):
        called["member_id"] = member_id
        return {"policies": [{"plan_code": "SILVER-PPO-01", "status": "active"}]}

    monkeypatch.setattr("chatbot.inquiry.nodes.member_coverage", coverage)
    facts = facts_for(
        {
            "member_id": "MBR-100231",
            "actor": ACTOR,
            "user_text": "Ok Policy details",
            "lookup": {"intent": "claims"},
        }
    )
    assert called["member_id"] == "MBR-100231"
    assert facts["policies"][0]["status"] == "active"


def test_unknown_question_does_not_read_claims(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("claims were read")

    monkeypatch.setattr("chatbot.inquiry.nodes.member_claims", fail)
    facts = facts_for({"member_id": "MBR-100231", "actor": ACTOR, "lookup": {"intent": "unknown"}})
    assert "claims" in facts["note"]


def test_provider_question_without_a_name_does_not_search(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("providers were searched")

    monkeypatch.setattr("chatbot.inquiry.nodes.find_providers", fail)
    facts = facts_for(
        {"member_id": "MBR-100231", "actor": ACTOR, "lookup": {"intent": "providers", "provider_query": None}}
    )
    assert facts["providers"] == []


def test_inquiry_rejects_another_member():
    with pytest.raises(ChatError) as caught:
        post_inquiry("MBR-200001", "What is my plan?", ACTOR)
    assert caught.value.status_code == 403


def test_inquiry_stores_a_reply_without_amending_a_claim(monkeypatch):
    monkeypatch.setattr(
        "chatbot.inquiry.nodes.choose_lookup",
        lambda state, config=None: Lookup(intent="unknown"),
    )
    monkeypatch.setattr(
        "chatbot.inquiry.nodes.write_answer",
        lambda state, config=None: "I can tell you about your claims, your plan, and providers on file.",
    )

    def fail(*_args, **_kwargs):
        raise AssertionError("an answer was posted")

    monkeypatch.setattr("chatbot.tools.payer.post_answer", fail)
    _clear(MEMBER)
    actor = {**ACTOR, "actor_id": MEMBER}
    with payer_engine().connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM claims.claim_amendment")).scalar_one()
    try:
        body = post_inquiry(MEMBER, "Please approve my claim.", actor)
    finally:
        _clear(MEMBER)
    with payer_engine().connect() as conn:
        after = conn.execute(text("SELECT count(*) FROM claims.claim_amendment")).scalar_one()
    assert after == before
    assert body["messages"][-1]["text"].startswith("I can tell you about your claims")
