"""SQLite database layer for the Smart Queue Management Bot (multi-tenant).

Uses Python's built-in ``sqlite3`` (no ORM) to keep dependencies minimal.
The database is a single file (``queue.db``) so it survives restarts and is
easy to inspect with any SQLite browser.

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

# queue.db lives in backend/ for local development. Hosted deployments can set
# QUEUEBOT_DB_PATH to a persistent disk path such as /data/queue.db.
DB_PATH = Path(os.environ.get("QUEUEBOT_DB_PATH", Path(__file__).resolve().parent.parent / "queue.db"))


def get_connection() -> sqlite3.Connection:
    """Open a connection with row access by column name and FK enforcement."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they do not exist."""
    conn = get_connection()
    try:
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
        conn.commit()
    finally:
        conn.close()
