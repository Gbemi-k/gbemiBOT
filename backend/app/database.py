"""Database layer for the Smart Queue Management Bot (multi-tenant).

Uses SQLite locally by default, and PostgreSQL when DATABASE_URL is set. Neon
provides a PostgreSQL DATABASE_URL, so production can keep data across deploys
without changing the application code.

Data model
----------
- An **account** is a business/organization (e.g. a hospital or bank). It owns
  its own services and gets a unique ``slug`` used to build its public join link.
- **sessions** hold login tokens for account owners.
- **services** belong to an account (a queue line: Doctor, Pharmacy, ...).
- **tickets** belong to a service; **notifications** are the bot messages per ticket.
"""

from __future__ import annotations

import sqlite3
import os
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # Local SQLite-only installs do not need psycopg.
    psycopg = None
    dict_row = None

# queue.db lives in backend/ for local development. Hosted deployments can set
# QUEUEBOT_DB_PATH to a persistent disk path such as /data/queue.db.
DB_PATH = Path(os.environ.get("QUEUEBOT_DB_PATH", Path(__file__).resolve().parent.parent / "queue.db"))
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))


class PostgresCursor:
    def __init__(self, cursor: Any, lastrowid: Optional[int] = None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PostgresConnection:
    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> PostgresCursor:
        converted = sql.replace("?", "%s")
        lower = converted.lstrip().lower()
        wants_id = (
            lower.startswith("insert into accounts")
            or lower.startswith("insert into services")
            or lower.startswith("insert into tickets")
            or lower.startswith("insert into notifications")
        ) and " returning " not in lower
        if wants_id:
            converted = converted.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.execute(converted, params)
        lastrowid = None
        if wants_id:
            row = cur.fetchone()
            lastrowid = row["id"] if row else None
        return PostgresCursor(cur, lastrowid)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self._conn.execute(statement)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def get_connection():
    """Open a connection with row access by column name and FK enforcement."""
    if USE_POSTGRES:
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set, but psycopg is not installed")
        return PostgresConnection(psycopg.connect(DATABASE_URL, row_factory=dict_row))

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they do not exist."""
    conn = get_connection()
    try:
        if USE_POSTGRES:
            conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS accounts (
                id            SERIAL PRIMARY KEY,
                name          TEXT NOT NULL,
                slug          TEXT NOT NULL UNIQUE,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token         TEXT PRIMARY KEY,
                account_id    INTEGER NOT NULL REFERENCES accounts(id),
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS services (
                id            SERIAL PRIMARY KEY,
                account_id    INTEGER NOT NULL REFERENCES accounts(id),
                name          TEXT NOT NULL,
                avg_minutes   REAL NOT NULL DEFAULT 5,
                active        INTEGER NOT NULL DEFAULT 1,
                status        TEXT NOT NULL DEFAULT 'open',
                UNIQUE (account_id, name)
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id            SERIAL PRIMARY KEY,
                service_id    INTEGER NOT NULL REFERENCES services(id),
                ticket_number INTEGER NOT NULL,
                name          TEXT NOT NULL,
                phone         TEXT,
                status        TEXT NOT NULL DEFAULT 'waiting',
                created_at    TEXT NOT NULL,
                called_at     TEXT,
                finished_at   TEXT,
                notified_almost INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id            SERIAL PRIMARY KEY,
                ticket_id     INTEGER NOT NULL REFERENCES tickets(id),
                kind          TEXT NOT NULL,
                message       TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_services_account
                ON services(account_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_service_status
                ON tickets(service_id, status);
            CREATE INDEX IF NOT EXISTS idx_notifications_ticket
                ON notifications(ticket_id);
                """
            )
            conn.execute("ALTER TABLE services ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open'")
        else:
            conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS accounts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,            -- organization name
                slug          TEXT NOT NULL UNIQUE,     -- used in the public join link
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token         TEXT PRIMARY KEY,
                account_id    INTEGER NOT NULL REFERENCES accounts(id),
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS services (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id    INTEGER NOT NULL REFERENCES accounts(id),
                name          TEXT NOT NULL,
                avg_minutes   REAL NOT NULL DEFAULT 5,
                active        INTEGER NOT NULL DEFAULT 1,
                status        TEXT NOT NULL DEFAULT 'open',
                UNIQUE (account_id, name)
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id    INTEGER NOT NULL REFERENCES services(id),
                ticket_number INTEGER NOT NULL,        -- per service, per day
                name          TEXT NOT NULL,
                phone         TEXT,
                status        TEXT NOT NULL DEFAULT 'waiting',
                                                       -- waiting | serving | served | cancelled | no_show
                created_at    TEXT NOT NULL,           -- ISO timestamp (join time)
                called_at     TEXT,                    -- moved to 'serving'
                finished_at   TEXT,                    -- moved to served/cancelled/no_show
                notified_almost INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id     INTEGER NOT NULL REFERENCES tickets(id),
                kind          TEXT NOT NULL,           -- joined | almost | your_turn | served | cancelled
                message       TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_services_account
                ON services(account_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_service_status
                ON tickets(service_id, status);
            CREATE INDEX IF NOT EXISTS idx_notifications_ticket
                ON notifications(ticket_id);
            """
            )
            columns = conn.execute("PRAGMA table_info(services)").fetchall()
            if not any(c["name"] == "status" for c in columns):
                conn.execute("ALTER TABLE services ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
        conn.commit()
    finally:
        conn.close()
