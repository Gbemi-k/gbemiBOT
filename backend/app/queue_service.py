"""Business logic for the Smart Queue Management Bot (multi-tenant).

All queue rules live here: joining, position/wait calculation, the staff
"call next" flow, cancellation, the bot-message (notification) engine, and
per-account service management. The web layer (main.py) is a thin wrapper.

Everything is scoped to an **account** (a business/organization). Services
belong to an account; tickets belong to a service; so a ticket's account is
implied by its service. Owner actions pass ``account_id`` and we verify the
target service really belongs to that account.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional

from .database import get_connection

# Fallback used only when a service has no completed visits yet to learn from.
DEFAULT_AVG_MINUTES = 5.0
# How many people from the front before the bot says "start coming".
ALMOST_THRESHOLD = 3

# Suggested services, grouped by industry. These are ONLY suggestions shown
# during dashboard setup — the owner chooses which (if any) to add, and can
# always add their own custom ones. Nothing is created automatically.
SERVICE_TEMPLATES = [
    {
        "category": "Hospital / Clinic",
        "icon": "health",
        "services": [
            {"name": "Doctor Consultation", "avg_minutes": 8},
            {"name": "Pharmacy", "avg_minutes": 4},
            {"name": "Laboratory", "avg_minutes": 6},
            {"name": "Reception", "avg_minutes": 3},
        ],
    },
    {
        "category": "Bank",
        "icon": "bank",
        "services": [
            {"name": "Deposits & Withdrawals", "avg_minutes": 5},
            {"name": "Account Opening", "avg_minutes": 12},
            {"name": "Loans & Enquiries", "avg_minutes": 10},
            {"name": "Customer Care", "avg_minutes": 6},
        ],
    },
    {
        "category": "Office / Government",
        "icon": "office",
        "services": [
            {"name": "General Enquiries", "avg_minutes": 5},
            {"name": "Document Submission", "avg_minutes": 7},
            {"name": "Payments", "avg_minutes": 4},
            {"name": "Collection", "avg_minutes": 4},
        ],
    },
]


def service_templates() -> list[dict[str, Any]]:
    """Return the suggested-service catalogue for the setup screen."""
    return SERVICE_TEMPLATES


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today_bounds() -> tuple[str, str]:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def _minutes_between(start_iso: Optional[str], end_iso: Optional[str]) -> Optional[float]:
    if not start_iso or not end_iso:
        return None
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
    except ValueError:
        return None
    minutes = (end - start).total_seconds() / 60
    return minutes if minutes > 0 else None


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 11 -> '11th', etc."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _service_row(conn: sqlite3.Connection, service_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown service")
    return row


def _owned_service(
    conn: sqlite3.Connection, service_id: int, account_id: int
) -> sqlite3.Row:
    """Fetch a service and confirm it belongs to the given account."""
    row = _service_row(conn, service_id)
    if row["account_id"] != account_id:
        raise ValueError("That service does not belong to your account")
    return row


def _now_serving(conn: sqlite3.Connection, service_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tickets WHERE service_id = ? AND status = 'serving' "
        "ORDER BY called_at LIMIT 1",
        (service_id,),
    ).fetchone()


# How strongly the configured/default time anchors the estimate. It behaves
# like "PRIOR_WEIGHT visits we've already seen at the configured pace", so the
# learned average only takes over once enough REAL visits have accumulated.
# This keeps estimates sensible early in the day (and during rapid testing,
# where serving people in seconds would otherwise collapse the average).
PRIOR_WEIGHT = 4


def _avg_minutes(conn: sqlite3.Connection, service_id: int) -> float:
    """Estimated minutes per visit: the configured time blended with today's
    measured times, weighted by how many real visits we've actually observed.

    effective = (configured * PRIOR_WEIGHT + measured_avg * n) / (PRIOR_WEIGHT + n)
    """
    svc = _service_row(conn, service_id)
    prior = float(svc["avg_minutes"] or DEFAULT_AVG_MINUTES)

    start, end = _today_bounds()
    rows = conn.execute(
        """
        SELECT called_at, finished_at
        FROM tickets
        WHERE service_id = ? AND status = 'served'
          AND called_at IS NOT NULL AND finished_at IS NOT NULL
          AND created_at >= ? AND created_at < ?
        """,
        (service_id, start, end),
    ).fetchall()

    durations = [
        m
        for m in (_minutes_between(r["called_at"], r["finished_at"]) for r in rows)
        if m is not None
    ]
    n = len(durations)
    measured = (sum(durations) / n) if n else None
    if not n or measured is None:
        return round(prior, 1)  # no real data yet → use the configured time

    blended = (prior * PRIOR_WEIGHT + measured * n) / (PRIOR_WEIGHT + n)
    return round(blended, 1)


def _position(conn: sqlite3.Connection, ticket: sqlite3.Row) -> int:
    """1-based position of a *waiting* ticket within its service line."""
    ahead = conn.execute(
        "SELECT COUNT(*) AS c FROM tickets "
        "WHERE service_id = ? AND status = 'waiting' AND id < ?",
        (ticket["service_id"], ticket["id"]),
    ).fetchone()["c"]
    return ahead + 1


def _add_notification(
    conn: sqlite3.Connection, ticket_id: int, kind: str, message: str
) -> None:
    conn.execute(
        "INSERT INTO notifications (ticket_id, kind, message, created_at) "
        "VALUES (?, ?, ?, ?)",
        (ticket_id, kind, message, _now()),
    )


def _recompute_almost(conn: sqlite3.Connection, service_id: int) -> None:
    """Fire a one-time 'start coming' alert for anyone now within the threshold."""
    waiting = conn.execute(
        "SELECT * FROM tickets WHERE service_id = ? AND status = 'waiting' "
        "ORDER BY id",
        (service_id,),
    ).fetchall()
    svc = _service_row(conn, service_id)
    for idx, t in enumerate(waiting, start=1):
        if idx <= ALMOST_THRESHOLD and not t["notified_almost"]:
            msg = (
                f"{t['name']}, please start coming — you're {_ordinal(idx)} in line "
                f"for {svc['name']}. You'll be attended to soon!"
            )
            _add_notification(conn, t["id"], "almost", msg)
            conn.execute(
                "UPDATE tickets SET notified_almost = 1 WHERE id = ?", (t["id"],)
            )


def _service_summary(conn: sqlite3.Connection, s: sqlite3.Row) -> dict[str, Any]:
    waiting = conn.execute(
        "SELECT COUNT(*) AS c FROM tickets "
        "WHERE service_id = ? AND status = 'waiting'",
        (s["id"],),
    ).fetchone()["c"]
    ns = _now_serving(conn, s["id"])
    return {
        "id": s["id"],
        "name": s["name"],
        "waiting": waiting,
        "now_serving": ns["ticket_number"] if ns else None,
        "avg_minutes": _avg_minutes(conn, s["id"]),
        "status": s["status"],
        "accepting": s["active"] == 1 and s["status"] == "open",
    }


# --------------------------------------------------------------------------- #
# Account / org lookups
# --------------------------------------------------------------------------- #
def get_account_by_slug(slug: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, slug FROM accounts WHERE slug = ?", (slug,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def public_org_view(slug: str) -> dict[str, Any]:
    """Org name + its active services — what the public join page shows."""
    conn = get_connection()
    try:
        acc = conn.execute(
            "SELECT id, name, slug FROM accounts WHERE slug = ?", (slug,)
        ).fetchone()
        if acc is None:
            raise ValueError("Organization not found")
        services = conn.execute(
            "SELECT * FROM services WHERE account_id = ? AND active = 1 AND status = 'open' ORDER BY name",
            (acc["id"],),
        ).fetchall()
        return {
            "name": acc["name"],
            "slug": acc["slug"],
            "services": [_service_summary(conn, s) for s in services],
        }
    finally:
        conn.close()


def public_display_view(slug: str) -> dict[str, Any]:
    """Read-only waiting-room display data for an organization's active services."""
    conn = get_connection()
    try:
        acc = conn.execute(
            "SELECT id, name, slug FROM accounts WHERE slug = ?", (slug,)
        ).fetchone()
        if acc is None:
            raise ValueError("Organization not found")
        services = conn.execute(
            "SELECT * FROM services WHERE account_id = ? AND active = 1 ORDER BY name",
            (acc["id"],),
        ).fetchall()
        out = []
        for s in services:
            ns = _now_serving(conn, s["id"])
            waiting_rows = conn.execute(
                """
                SELECT ticket_number
                FROM tickets
                WHERE service_id = ? AND status = 'waiting'
                ORDER BY id
                LIMIT 5
                """,
                (s["id"],),
            ).fetchall()
            waiting_count = conn.execute(
                "SELECT COUNT(*) AS c FROM tickets WHERE service_id = ? AND status = 'waiting'",
                (s["id"],),
            ).fetchone()["c"]
            out.append(
                {
                    "id": s["id"],
                    "name": s["name"],
                    "status": s["status"],
                    "now_serving": ns["ticket_number"] if ns else None,
                    "waiting_count": waiting_count,
                    "next_tickets": [w["ticket_number"] for w in waiting_rows],
                }
            )
        return {
            "name": acc["name"],
            "slug": acc["slug"],
            "updated_at": _now(),
            "services": out,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Service management (owner)
# --------------------------------------------------------------------------- #
def list_services(account_id: int) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        services = conn.execute(
            "SELECT * FROM services WHERE account_id = ? AND active = 1 ORDER BY name",
            (account_id,),
        ).fetchall()
        return [_service_summary(conn, s) for s in services]
    finally:
        conn.close()


def add_service(account_id: int, name: str, avg_minutes: float) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Service name is required")
    try:
        avg_minutes = float(avg_minutes)
    except (TypeError, ValueError):
        avg_minutes = DEFAULT_AVG_MINUTES
    if avg_minutes <= 0:
        avg_minutes = DEFAULT_AVG_MINUTES

    conn = get_connection()
    try:
        exists = conn.execute(
            "SELECT 1 FROM services WHERE account_id = ? AND name = ? AND active = 1",
            (account_id, name),
        ).fetchone()
        if exists:
            raise ValueError("You already have a service with that name")
        cur = conn.execute(
            "INSERT INTO services (account_id, name, avg_minutes) VALUES (?, ?, ?)",
            (account_id, name, avg_minutes),
        )
        conn.commit()
        s = conn.execute(
            "SELECT * FROM services WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return _service_summary(conn, s)
    finally:
        conn.close()


def add_services_bulk(
    account_id: int, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Add several services at once (used by the setup screen).

    Each item is ``{"name": str, "avg_minutes": number}``. Duplicates (a name
    the account already has) are silently skipped so the call is idempotent.
    Returns the account's full, updated service list.
    """
    conn = get_connection()
    try:
        existing = {
            r["name"].lower()
            for r in conn.execute(
                "SELECT name FROM services WHERE account_id = ? AND active = 1",
                (account_id,),
            ).fetchall()
        }
        for item in items:
            name = (item.get("name") or "").strip()
            if not name or name.lower() in existing:
                continue
            try:
                avg = float(item.get("avg_minutes", DEFAULT_AVG_MINUTES))
            except (TypeError, ValueError):
                avg = DEFAULT_AVG_MINUTES
            if avg <= 0:
                avg = DEFAULT_AVG_MINUTES
            conn.execute(
                "INSERT INTO services (account_id, name, avg_minutes) VALUES (?, ?, ?)",
                (account_id, name, avg),
            )
            existing.add(name.lower())
        conn.commit()
        return list_services(account_id)
    finally:
        conn.close()


def remove_service(account_id: int, service_id: int) -> None:
    """Soft-delete a service (kept for historical reports)."""
    conn = get_connection()
    try:
        _owned_service(conn, service_id, account_id)
        conn.execute("UPDATE services SET active = 0 WHERE id = ?", (service_id,))
        conn.commit()
    finally:
        conn.close()


def set_service_status(account_id: int, service_id: int, status: str) -> dict[str, Any]:
    """Pause, open, or close an active service line."""
    status = (status or "").strip().lower()
    if status not in {"open", "paused", "closed"}:
        raise ValueError("Unknown service status")
    conn = get_connection()
    try:
        svc = _owned_service(conn, service_id, account_id)
        conn.execute("UPDATE services SET status = ? WHERE id = ?", (status, service_id))
        conn.commit()
        updated = conn.execute("SELECT * FROM services WHERE id = ?", (svc["id"],)).fetchone()
        return _service_summary(conn, updated)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Queue actions
# --------------------------------------------------------------------------- #
def join_queue(
    account_id: int, service_id: int, name: str, phone: Optional[str]
) -> dict[str, Any]:
    """Register a person into a service line and issue a ticket."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required")

    conn = get_connection()
    try:
        svc = _owned_service(conn, service_id, account_id)
        if svc["status"] != "open":
            raise ValueError(f"{svc['name']} is {svc['status']} right now")

        # Per-service, per-day ticket number.
        start, end = _today_bounds()
        last = conn.execute(
            "SELECT MAX(ticket_number) AS n FROM tickets "
            "WHERE service_id = ? AND created_at >= ? AND created_at < ?",
            (service_id, start, end),
        ).fetchone()["n"]
        ticket_number = (last or 0) + 1

        cur = conn.execute(
            "INSERT INTO tickets (service_id, ticket_number, name, phone, status, created_at) "
            "VALUES (?, ?, ?, ?, 'waiting', ?)",
            (service_id, ticket_number, name, (phone or "").strip() or None, _now()),
        )
        ticket_id = cur.lastrowid

        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        position = _position(conn, ticket)
        ns = _now_serving(conn, service_id)

        welcome = (
            f"Hello {name}! Your ticket number is {ticket_number} for {svc['name']}. "
            f"You're {_ordinal(position)} in line. "
            f"Now serving: {ns['ticket_number'] if ns else '—'}. "
            f"I'll alert you when you're {ALMOST_THRESHOLD} people away."
        )
        _add_notification(conn, ticket_id, "joined", welcome)
        _recompute_almost(conn, service_id)
        conn.commit()
        return _ticket_status(conn, ticket_id)
    finally:
        conn.close()


def _ticket_status(conn: sqlite3.Connection, ticket_id: int) -> dict[str, Any]:
    t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if t is None:
        raise ValueError("Ticket not found")
    svc = _service_row(conn, t["service_id"])
    ns = _now_serving(conn, t["service_id"])

    position = _position(conn, t) if t["status"] == "waiting" else 0
    avg = _avg_minutes(conn, t["service_id"])
    est_wait = round(position * avg) if t["status"] == "waiting" else 0

    messages = conn.execute(
        "SELECT kind, message, created_at FROM notifications "
        "WHERE ticket_id = ? ORDER BY id",
        (ticket_id,),
    ).fetchall()

    return {
        "ticket_id": t["id"],
        "ticket_number": t["ticket_number"],
        "name": t["name"],
        "phone": t["phone"],
        "service": svc["name"],
        "service_id": svc["id"],
        "status": t["status"],
        "position": position,
        "now_serving": ns["ticket_number"] if ns else None,
        "people_ahead": max(position - 1, 0),
        "estimated_wait_minutes": est_wait,
        "created_at": t["created_at"],
        "messages": [dict(m) for m in messages],
    }


def get_ticket(ticket_id: int) -> dict[str, Any]:
    """Full live status of a ticket, including the bot message feed."""
    conn = get_connection()
    try:
        return _ticket_status(conn, ticket_id)
    finally:
        conn.close()


def cancel_ticket(ticket_id: int) -> dict[str, Any]:
    """Let a waiting person leave the queue."""
    conn = get_connection()
    try:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            raise ValueError("Ticket not found")
        if t["status"] not in ("waiting", "serving"):
            return _ticket_status(conn, ticket_id)  # already finished
        svc = _service_row(conn, t["service_id"])
        conn.execute(
            "UPDATE tickets SET status = 'cancelled', finished_at = ? WHERE id = ?",
            (_now(), ticket_id),
        )
        _add_notification(
            conn,
            ticket_id,
            "cancelled",
            f"{t['name']}, you've left the {svc['name']} queue "
            f"(ticket {t['ticket_number']}). Come back anytime!",
        )
        _recompute_almost(conn, t["service_id"])
        conn.commit()
        return _ticket_status(conn, ticket_id)
    finally:
        conn.close()


def call_next(account_id: int, service_id: int) -> dict[str, Any]:
    """Complete whoever is being served, then call the next waiting person."""
    conn = get_connection()
    try:
        svc = _owned_service(conn, service_id, account_id)
        if svc["status"] == "closed":
            raise ValueError(f"{svc['name']} is closed")

        # 1) Finish the person currently at the counter.
        current = _now_serving(conn, service_id)
        if current is not None:
            conn.execute(
                "UPDATE tickets SET status = 'served', finished_at = ? WHERE id = ?",
                (_now(), current["id"]),
            )
            _add_notification(
                conn,
                current["id"],
                "served",
                f"Thanks {current['name']}, your {svc['name']} visit is complete. "
                f"Have a great day!",
            )

        # 2) Call the next waiting person (lowest id = earliest join).
        nxt = conn.execute(
            "SELECT * FROM tickets WHERE service_id = ? AND status = 'waiting' "
            "ORDER BY id LIMIT 1",
            (service_id,),
        ).fetchone()
        called = None
        if nxt is not None:
            conn.execute(
                "UPDATE tickets SET status = 'serving', called_at = ? WHERE id = ?",
                (_now(), nxt["id"]),
            )
            _add_notification(
                conn,
                nxt["id"],
                "your_turn",
                f"It's your turn, {nxt['name']}! Please proceed to {svc['name']} "
                f"(ticket {nxt['ticket_number']}).",
            )
            called = nxt

        _recompute_almost(conn, service_id)
        conn.commit()

        return {
            "service": svc["name"],
            "service_id": service_id,
            "completed": current["ticket_number"] if current else None,
            "now_serving": called["ticket_number"] if called else None,
            "now_serving_name": called["name"] if called else None,
            "queue_empty": called is None,
        }
    finally:
        conn.close()


def mark_no_show(account_id: int, service_id: int) -> dict[str, Any]:
    """Mark the current person as no-show, then call the next waiting person."""
    conn = get_connection()
    try:
        svc = _owned_service(conn, service_id, account_id)
        current = _now_serving(conn, service_id)
        if current is None:
            raise ValueError("No one is currently being served")
        conn.execute(
            "UPDATE tickets SET status = 'no_show', finished_at = ? WHERE id = ?",
            (_now(), current["id"]),
        )
        _add_notification(
            conn,
            current["id"],
            "no_show",
            f"{current['name']}, ticket {current['ticket_number']} was marked as no-show for {svc['name']}.",
        )
        nxt = conn.execute(
            "SELECT * FROM tickets WHERE service_id = ? AND status = 'waiting' ORDER BY id LIMIT 1",
            (service_id,),
        ).fetchone()
        called = None
        if nxt is not None and svc["status"] != "closed":
            conn.execute(
                "UPDATE tickets SET status = 'serving', called_at = ? WHERE id = ?",
                (_now(), nxt["id"]),
            )
            _add_notification(
                conn,
                nxt["id"],
                "your_turn",
                f"It's your turn, {nxt['name']}! Please proceed to {svc['name']} "
                f"(ticket {nxt['ticket_number']}).",
            )
            called = nxt
        _recompute_almost(conn, service_id)
        conn.commit()
        return {
            "service": svc["name"],
            "service_id": service_id,
            "no_show": current["ticket_number"],
            "now_serving": called["ticket_number"] if called else None,
            "now_serving_name": called["name"] if called else None,
            "queue_empty": called is None,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Owner dashboard data
# --------------------------------------------------------------------------- #
def staff_overview(account_id: int) -> list[dict[str, Any]]:
    """Per-service view for the dashboard: now serving + waiting list."""
    conn = get_connection()
    try:
        services = conn.execute(
            "SELECT * FROM services WHERE account_id = ? AND active = 1 ORDER BY name",
            (account_id,),
        ).fetchall()
        out = []
        for s in services:
            ns = _now_serving(conn, s["id"])
            waiting_rows = conn.execute(
                "SELECT ticket_number, name, created_at FROM tickets "
                "WHERE service_id = ? AND status = 'waiting' ORDER BY id",
                (s["id"],),
            ).fetchall()
            out.append(
                {
                    "id": s["id"],
                    "name": s["name"],
                    "avg_minutes": _avg_minutes(conn, s["id"]),
                    "status": s["status"],
                    "now_serving": (
                        {"ticket_number": ns["ticket_number"], "name": ns["name"]}
                        if ns
                        else None
                    ),
                    "waiting": [dict(w) for w in waiting_rows],
                    "waiting_count": len(waiting_rows),
                }
            )
        return out
    finally:
        conn.close()


def daily_report(account_id: int) -> dict[str, Any]:
    """Summary of today's activity for this account's report page."""
    conn = get_connection()
    try:
        start, end = _today_bounds()
        rows = conn.execute(
            """
            SELECT s.id AS service_id, s.name AS service, t.id, t.status, t.called_at, t.finished_at
            FROM services s
            LEFT JOIN tickets t
                   ON t.service_id = s.id
                  AND t.created_at >= ? AND t.created_at < ?
            WHERE s.account_id = ? AND s.active = 1
            ORDER BY s.name
            """,
            (start, end, account_id),
        ).fetchall()
        totals = {"issued": 0, "served": 0, "cancelled": 0, "waiting": 0, "serving": 0, "no_show": 0}
        grouped: dict[int, dict[str, Any]] = {}
        for r in rows:
            item = grouped.setdefault(
                r["service_id"],
                {"service": r["service"], "issued": 0, "served": 0, "cancelled": 0, "no_show": 0, "_durations": []},
            )
            if r["id"] is None:
                continue
            status = r["status"]
            totals["issued"] += 1
            item["issued"] += 1
            if status in totals:
                totals[status] += 1
            if status in item:
                item[status] += 1
            if status == "served":
                minutes = _minutes_between(r["called_at"], r["finished_at"])
                if minutes is not None:
                    item["_durations"].append(minutes)

        per_service = []
        for item in grouped.values():
            durations = item.pop("_durations")
            item["avg_service_minutes"] = round(sum(durations) / len(durations), 1) if durations else None
            per_service.append(item)

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "totals": totals,
            "per_service": per_service,
        }
    finally:
        conn.close()
