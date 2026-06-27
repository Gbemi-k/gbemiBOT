"""Authentication for account owners.

Email + password with PBKDF2-hashed passwords and random session tokens —
all from the standard library (no extra dependencies). Tokens are returned to
the browser, stored client-side, and sent back as ``Authorization: Bearer``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime
from typing import Any, Optional

from .database import get_connection

PBKDF2_ROUNDS = 200_000
MIN_PASSWORD_LEN = 6


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS
    ).hex()


def _slugify(name: str) -> str:
    """Turn an org name into a URL-safe slug + a short random suffix.

    The random suffix guarantees uniqueness and makes links hard to guess.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"
    base = base[:40]
    return f"{base}-{secrets.token_hex(2)}"


def _account_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "email": row["email"],
    }


def _new_session(conn: sqlite3.Connection, account_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token, account_id, created_at) VALUES (?, ?, ?)",
        (token, account_id, _now()),
    )
    return token


def signup(name: str, email: str, password: str) -> dict[str, Any]:
    """Create a new business account, seed its services, and log it in."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name:
        raise ValueError("Organization name is required")
    if not email or "@" not in email:
        raise ValueError("A valid email is required")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters")

    conn = get_connection()
    try:
        if conn.execute("SELECT 1 FROM accounts WHERE email = ?", (email,)).fetchone():
            raise ValueError("An account with this email already exists")

        salt = secrets.token_hex(16)
        password_hash = _hash_password(password, salt)

        slug = _slugify(name)
        while conn.execute("SELECT 1 FROM accounts WHERE slug = ?", (slug,)).fetchone():
            slug = _slugify(name)

        cur = conn.execute(
            "INSERT INTO accounts (name, slug, email, password_hash, salt, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, slug, email, password_hash, salt, _now()),
        )
        account_id = cur.lastrowid
        # NOTE: we intentionally do NOT create any services here. The owner
        # decides which services they offer during the dashboard setup step
        # (and can add/remove more at any time afterwards).
        token = _new_session(conn, account_id)
        conn.commit()

        row = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return {"token": token, "account": _account_public(row)}
    finally:
        conn.close()


def login(email: str, password: str) -> dict[str, Any]:
    """Verify credentials and start a session."""
    email = (email or "").strip().lower()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM accounts WHERE email = ?", (email,)
        ).fetchone()
        if row is None:
            raise ValueError("Invalid email or password")
        candidate = _hash_password(password or "", row["salt"])
        if not hmac.compare_digest(candidate, row["password_hash"]):
            raise ValueError("Invalid email or password")

        token = _new_session(conn, row["id"])
        conn.commit()
        return {"token": token, "account": _account_public(row)}
    finally:
        conn.close()


def logout(token: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def account_for_token(token: Optional[str]) -> Optional[dict[str, Any]]:
    """Resolve a bearer token to its account, or None if invalid."""
    if not token:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT a.* FROM sessions s JOIN accounts a ON a.id = s.account_id "
            "WHERE s.token = ?",
            (token,),
        ).fetchone()
        return _account_public(row) if row else None
    finally:
        conn.close()
