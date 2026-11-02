"""OpenAI model used by the missing-info chatbot. There is no stand-in."""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI


def chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ.get("CHATBOT_MODEL", "gpt-4o-mini"),
        temperature=0,
        api_key=os.environ["OPENAI_API_KEY"],
    )
