"""Sign-in for the portal. The session token, not the browser headers, decides the role."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from portal.app.db import portal_engine
from portal.app.passwords import verify_password

router = APIRouter()


class LoginBody(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


def _public(row, token: str | None = None) -> dict:
    body = {
        "user_id": row["user_id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "role": row["role"],
        "actor_type": row["actor_type"],
        "submitter_id": row["submitter_id"],
    }
    if token is not None:
        body["token"] = token
    return body


def current_user(request: Request) -> dict | None:
    if getattr(request.state, "auth_checked", False):
        return getattr(request.state, "auth_user", None)
    request.state.auth_checked = True
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    request.state.auth_user = _load(token) if token else None
    return request.state.auth_user


def _load(token: str) -> dict | None:
    with portal_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT u.user_id, u.email, u.display_name, u.role, u.actor_type, u.submitter_id
                FROM portal.login_session s
                JOIN portal.app_user u ON u.user_id = s.user_id
                WHERE s.token = :token AND s.expires_at > now()
                """
            ),
            {"token": token},
        ).mappings().first()
    return _public(row) if row else None


@router.post("/auth/login")
def login(body: LoginBody):
    email = body.email.strip().lower()
    with portal_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT user_id, email, display_name, password_hash, role, actor_type, submitter_id
                FROM portal.app_user
                WHERE lower(email) = :email
                """
            ),
            {"email": email},
        ).mappings().first()
        if row is None or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Email or password is not recognized")
        token = secrets.token_urlsafe(32)
        conn.execute(
            text(
                """
                INSERT INTO portal.login_session (token, user_id, expires_at)
                VALUES (:token, :user_id, now() + interval '12 hours')
                """
            ),
            {"token": token, "user_id": row["user_id"]},
        )
    return _public(row, token)


@router.get("/auth/me")
def me(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


@router.post("/auth/logout")
def logout(request: Request):
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if token:
        with portal_engine().begin() as conn:
            conn.execute(text("DELETE FROM portal.login_session WHERE token = :token"), {"token": token})
    return {"ok": True}
