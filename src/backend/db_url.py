"""Database URLs. The portal uses the owner URL. The payer service uses payer_app."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _psycopg(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def database_url() -> str:
    return _psycopg(os.environ["DATABASE_URL"])


def payer_database_url() -> str:
    parsed = urlparse(database_url())
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    password = quote(os.environ["PAYER_APP_PASSWORD"], safe="")
    name = parsed.path.lstrip("/")
    return f"postgresql+psycopg://payer_app:{password}@{host}:{port}/{name}"


def document_root() -> Path:
    configured = os.environ.get("DOCUMENT_ROOT", "data/documents")
    path = Path(configured)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def inbox_dir() -> Path:
    configured = os.environ.get("INBOX_DIR", "data/inbox")
    path = Path(configured)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path
