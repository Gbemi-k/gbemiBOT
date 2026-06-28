"""FastAPI application for the Smart Queue Management Bot (multi-tenant).

Each business owner signs up, gets a unique public join link, and manages
their own queues from a dashboard. Customers use the link (no account needed).

Routes are grouped as:
  - /api/auth/*    sign up, log in, who-am-i, log out
  - /api/owner/*   protected — operate only on the logged-in account's data
  - /api/public/*  open — the per-org join experience (by slug)
  - /api/queue/*   open — a single customer's ticket (track / cancel)
  - /q/{slug}      serves the public join page for an organization

Run from the ``backend`` folder:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, queue_service
from .database import init_db

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(
    title="Smart Queue Management Bot",
    description="Multi-tenant queue simulation: sign up, share your link, manage your queue.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# --------------------------------------------------------------------------- #
# Auth dependency
# --------------------------------------------------------------------------- #
def current_account(authorization: Optional[str] = Header(default=None)) -> dict:
    """Resolve the Bearer token into an account, or 401."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    account = auth.account_for_token(token)
    if account is None:
        raise HTTPException(status_code=401, detail="Please log in to continue")
    return account


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


class JoinRequest(BaseModel):
    service_id: int
    name: str = Field(min_length=1, max_length=80)
    phone: Optional[str] = Field(default=None, max_length=30)


class NextRequest(BaseModel):
    service_id: int


class ServiceStatusRequest(BaseModel):
    status: str = Field(pattern="^(open|paused|closed)$")


class ServiceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    avg_minutes: float = Field(default=5, gt=0, le=600)


class ServiceItem(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    avg_minutes: float = Field(default=5, gt=0, le=600)


class BulkServiceRequest(BaseModel):
    services: list[ServiceItem]


# --------------------------------------------------------------------------- #
# Auth routes
# --------------------------------------------------------------------------- #
@app.post("/api/auth/signup")
def signup(req: SignupRequest):
    try:
        return auth.signup(req.name, req.email, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/auth/login")
def login(req: LoginRequest):
    try:
        return auth.login(req.email, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        auth.logout(authorization[7:].strip())
    return {"ok": True}


@app.get("/api/auth/me")
def me(account: dict = Depends(current_account)):
    return account


# --------------------------------------------------------------------------- #
# Owner routes (protected — always scoped to the logged-in account)
# --------------------------------------------------------------------------- #
@app.get("/api/owner/overview")
def owner_overview(account: dict = Depends(current_account)):
    return queue_service.staff_overview(account["id"])


@app.post("/api/owner/next")
def owner_next(req: NextRequest, account: dict = Depends(current_account)):
    try:
        return queue_service.call_next(account["id"], req.service_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/owner/no-show")
def owner_no_show(req: NextRequest, account: dict = Depends(current_account)):
    try:
        return queue_service.mark_no_show(account["id"], req.service_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/owner/report")
def owner_report(account: dict = Depends(current_account)):
    return queue_service.daily_report(account["id"])


@app.get("/api/owner/services")
def owner_services(account: dict = Depends(current_account)):
    return queue_service.list_services(account["id"])


@app.post("/api/owner/services")
def owner_add_service(req: ServiceRequest, account: dict = Depends(current_account)):
    try:
        return queue_service.add_service(account["id"], req.name, req.avg_minutes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/owner/services/bulk")
def owner_add_services_bulk(
    req: BulkServiceRequest, account: dict = Depends(current_account)
):
    items = [{"name": s.name, "avg_minutes": s.avg_minutes} for s in req.services]
    return queue_service.add_services_bulk(account["id"], items)


@app.delete("/api/owner/services/{service_id}")
def owner_remove_service(service_id: int, account: dict = Depends(current_account)):
    try:
        queue_service.remove_service(account["id"], service_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/owner/services/{service_id}/status")
def owner_service_status(
    service_id: int, req: ServiceStatusRequest, account: dict = Depends(current_account)
):
    try:
        return queue_service.set_service_status(account["id"], service_id, req.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- #
# Public routes (no auth) — the customer join experience
# --------------------------------------------------------------------------- #
@app.get("/api/public/org/{slug}")
def public_org(slug: str):
    try:
        return queue_service.public_org_view(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/public/org/{slug}/join")
def public_join(slug: str, req: JoinRequest):
    org = queue_service.get_account_by_slug(slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        return queue_service.join_queue(org["id"], req.service_id, req.name, req.phone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/queue/ticket/{ticket_id}")
def ticket(ticket_id: int):
    try:
        return queue_service.get_ticket(ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/queue/cancel/{ticket_id}")
def cancel(ticket_id: int):
    try:
        return queue_service.cancel_ticket(ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/service-templates")
def service_templates():
    """Suggested services (by industry) shown on the dashboard setup screen."""
    return queue_service.service_templates()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Frontend pages
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/dashboard")
@app.get("/dashboard.html")
def dashboard():
    return FileResponse(FRONTEND_DIR / "dashboard.html")


@app.get("/q/{slug}")
def join_page(slug: str):
    # The page reads the slug from the URL and fetches the org via the API.
    return FileResponse(FRONTEND_DIR / "join.html")


# Static assets (css/js) and any other files. Mounted last so /api and the
# explicit routes above take precedence.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
