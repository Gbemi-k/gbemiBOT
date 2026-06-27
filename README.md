# 🤖 Smart Queue Management Bot

A **multi-tenant** web app for managing queues. A business (hospital, bank, office…)
**creates an account**, gets its **own private link**, and shares it. Their customers
open the link, **join the queue remotely**, **track their position live**, and get
**bot alerts** as their turn approaches — while staff call the next person from a
private dashboard.

This is the **simulation build**: bot messages appear on screen instead of going out
as real SMS, so it runs with **zero external accounts or API keys**. The notification
layer is isolated, so real SMS/WhatsApp can be dropped in later (see [Going further](#-going-further)).

---

## ✨ How it works

1. **A business signs up** at the home page (organization name + email + password).
2. They land on a **dashboard** showing their unique customer link, e.g.
   `http://127.0.0.1:8000/q/city-hospital-a3f9`.
3. They **share that link** with customers (print it, text it, QR code on the door).
4. **Customers open the link** (no account needed), pick a service, and join *that
   organization's* queue.
5. **Staff call the next person** from the dashboard; everyone's position and the
   bot messages update automatically.

Each account is fully isolated — one business never sees another's queues.

---

## 🧩 Features

- **Accounts & auth** — sign up / log in (passwords hashed with PBKDF2, token sessions)
- **Per-account share link** (`/q/{slug}`) — unguessable, ready to hand out
- **Customer join page** — pick a service, get a ticket, no sign-up
- **Live position tracking** + a chat-style **bot message feed**
  (welcome → "start coming" at 3-away → "it's your turn" → "visit complete")
- **Estimated wait time** that *learns* from real service durations during the day
- **Cancel** — leaving re-shifts the queue for everyone behind
- **Owner dashboard** — call-next board, **manage your own services**, and a **daily report**

---

## 🧱 Tech stack

| Layer     | Choice                                  |
|-----------|-----------------------------------------|
| Backend   | Python + **FastAPI** (Uvicorn)          |
| Auth      | PBKDF2 password hashing + token sessions (stdlib only) |
| Database  | **SQLite** (single file, no setup)      |
| Frontend  | Vanilla HTML / CSS / JS (no build step) |
| Realtime  | Lightweight polling every 3 seconds     |

No ORM, no bundler, **no third-party auth library** — easy to read and extend.

---

## 🚀 Quick start

### Windows (PowerShell)
```powershell
./run.ps1
```
### macOS / Linux / Git Bash
```bash
./run.sh
```

Then open **http://127.0.0.1:8000/**, create an account, and copy your customer link
from the dashboard. Open that link in another tab/phone to join as a customer.

> Interactive API docs are at **http://127.0.0.1:8000/docs**.

---

## 🕹️ Try the demo

1. Open **http://127.0.0.1:8000/** → **Create account** (e.g. "City Hospital").
2. On the dashboard, click **Copy** on your queue link, then **Open** it in a new tab.
3. In that customer tab: pick *Consultation*, enter a name, **Join queue** → you get a
   ticket and a bot welcome message.
4. Back on the dashboard (**Queue** tab) → click **Call next person**.
5. Watch the customer tab update live; the bot posts "it's your turn".
6. Check the **Report** tab for the day's totals, or the **Services** tab to add your
   own service lines.

---

## 📁 Project structure

```
gbemiBOT/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app: auth / owner / public routes + serves the frontend
│   │   ├── auth.py            # signup, login, password hashing, token sessions
│   │   ├── queue_service.py   # account-scoped queue logic + bot-message engine
│   │   └── database.py        # SQLite schema (accounts, sessions, services, tickets…)
│   ├── requirements.txt
│   └── queue.db               # created on first run
├── frontend/
│   ├── index.html             # landing + sign up / log in
│   ├── dashboard.html         # owner: share link, call-next, services, report
│   ├── join.html              # public customer join page (served at /q/{slug})
│   ├── css/style.css
│   └── js/{auth,dashboard,join}.js
├── run.ps1 / run.sh           # one-command launchers
└── README.md
```

---

## 🔌 API reference

**Auth**
| Method | Endpoint            | Purpose                          |
|--------|---------------------|----------------------------------|
| POST   | `/api/auth/signup`  | Create a business account        |
| POST   | `/api/auth/login`   | Log in → returns a token         |
| GET    | `/api/auth/me`      | Current account (needs token)    |
| POST   | `/api/auth/logout`  | End the session                  |

**Owner** (require `Authorization: Bearer <token>`; always scoped to that account)
| Method | Endpoint                        | Purpose                         |
|--------|---------------------------------|---------------------------------|
| GET    | `/api/owner/overview`           | Call-next board data            |
| POST   | `/api/owner/next`               | Complete current + call next    |
| GET    | `/api/owner/report`             | Today's totals & per-service    |
| GET/POST| `/api/owner/services`          | List / add services             |
| DELETE | `/api/owner/services/{id}`      | Remove a service                |

**Public** (no auth — the customer experience)
| Method | Endpoint                          | Purpose                       |
|--------|-----------------------------------|-------------------------------|
| GET    | `/api/public/org/{slug}`          | Org name + its services       |
| POST   | `/api/public/org/{slug}/join`     | Join a queue → returns ticket |
| GET    | `/api/queue/ticket/{id}`          | Live ticket status + bot feed |
| POST   | `/api/queue/cancel/{id}`          | Leave the queue               |

---

## ⚙️ Configuration

New accounts start with a few default services (seeded in
[`backend/app/database.py`](backend/app/database.py) → `DEFAULT_SERVICES`); owners then
add/remove their own from the **Services** tab. Delete `backend/queue.db` to wipe all
accounts and data.

---

## 🔭 Going further

The bot messages are written through a single notification layer (`_add_notification`
in `queue_service.py`). To send **real** notifications, add an adapter there:

- **SMS** — Twilio (needs your Account SID + Auth Token)
- **WhatsApp** — Twilio WhatsApp or the Meta WhatsApp Business API
- **Email** — SendGrid / Resend (free tiers)

Other natural next steps: per-service multiple counters, QR-code generation for the
share link, session expiry/refresh, password reset, and WebSocket push instead of polling.

---

*Built as a simulation first — designed to grow into a real system.*
