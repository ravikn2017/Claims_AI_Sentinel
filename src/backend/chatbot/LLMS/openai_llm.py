"""OpenAI model used by the missing-info chatbot. There is no stand-in."""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI


def chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ.get("CHATBOT_MODEL", "gpt-6-luna"),
        temperature=0,
        # Chat Completions tool calls on this model require reasoning off.
        reasoning_effort="none",
        api_key=os.environ["OPENAI_API_KEY"],
    )
