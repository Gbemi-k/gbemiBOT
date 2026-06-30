/* ============================================================================
   Public join page (served at /q/{slug})
   A customer opens their organization's link, joins a queue, and tracks their
   ticket live: position, estimated wait, and the bot's messages. The active
   ticket is remembered per-org in localStorage so a refresh keeps tracking it.
   (One ticket per device — the real-world customer experience.)
   ========================================================================== */

const slug = decodeURIComponent(window.location.pathname.split("/q/")[1] || "").replace(/\/$/, "");
const STORAGE_KEY = `queuebot.ticket.${slug}`;
let pollTimer = null;
let renderedMsgCount = 0;     // how many bot messages are already on screen
let lastStatus = null;        // previous status (used to fire the "your turn" celebration)
const TERMINAL_STATUSES = new Set(["served", "cancelled", "no_show"]);

const BOT_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4M8 16h0M16 16h0"/></svg>`;

// One-time cleanup of any leftover multi-person test data from earlier builds.
localStorage.removeItem(`queuebot.tickets.${slug}`);

/* ---- helpers ------------------------------------------------------------- */
async function api(path, options) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2600);
}
function fmtTime(iso) { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

// Smoothly tween a stat number to its new value.
function animateCount(el, target) {
  if (typeof target !== "number" || Number.isNaN(target)) { el.textContent = "—"; return; }
  const from = parseInt(el.textContent, 10);
  const start = Number.isNaN(from) ? 0 : from;
  if (start === target) { el.textContent = target; return; }
  const dur = 450, t0 = performance.now();
  (function step(now) {
    const p = Math.min((now - t0) / dur, 1);
    el.textContent = Math.round(start + (target - start) * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(step);
  })(performance.now());
}
function celebrate() {
  const colors = ["#6366f1", "#4f46e5", "#22d3ee", "#ec4899", "#15a34a"];
  for (let i = 0; i < 46; i++) {
    const c = document.createElement("div");
    c.className = "confetti";
    c.style.left = Math.random() * 100 + "vw";
    c.style.background = colors[i % colors.length];
    c.style.animationDuration = 2 + Math.random() * 1.5 + "s";
    c.style.animationDelay = Math.random() * 0.3 + "s";
    document.body.appendChild(c);
    setTimeout(() => c.remove(), 4000);
  }
}

/* ---- load the organization + its services -------------------------------- */
async function loadOrg() {
  try {
    const org = await api(`/api/public/org/${encodeURIComponent(slug)}`);
    document.getElementById("orgTitle").textContent = org.name;
    document.getElementById("joinHeading").textContent = `Join the queue at ${org.name}`;
    document.title = `Join the queue — ${org.name}`;
    const select = document.getElementById("service");
    if (!org.services.length) {
      select.innerHTML = `<option>No services available right now</option>`;
      document.querySelector("#joinForm button").disabled = true;
      return;
    }
    select.innerHTML = org.services
      .map((s) => `<option value="${s.id}">${s.name} — ${s.waiting} waiting (~${s.avg_minutes} min)</option>`)
      .join("");
  } catch {
    document.getElementById("main").classList.add("hidden");
    document.getElementById("notFound").classList.remove("hidden");
  }
}

/* ---- join ---------------------------------------------------------------- */
document.getElementById("joinForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = ev.target.querySelector("button");
  btn.disabled = true;
  try {
    const ticket = await api(`/api/public/org/${encodeURIComponent(slug)}/join`, {
      method: "POST",
      body: JSON.stringify({
        service_id: Number(document.getElementById("service").value),
        name: document.getElementById("name").value,
        phone: document.getElementById("phone").value,
      }),
    });
    localStorage.setItem(STORAGE_KEY, ticket.ticket_id);
    resetView();
    render(ticket);
    startPolling();
    toast(`You're in! Ticket #${ticket.ticket_number}`);
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---- cancel -------------------------------------------------------------- */
document.getElementById("cancelBtn").addEventListener("click", async () => {
  const id = localStorage.getItem(STORAGE_KEY);
  if (!id) return;
  if (!confirm("Leave the queue? You'll lose your spot.")) return;
  try {
    render(await api(`/api/queue/cancel/${id}`, { method: "POST" }));
    stopPolling();
    toast("You've left the queue.");
  } catch (e) {
    toast(e.message);
  }
});

/* ---- join again ---------------------------------------------------------- */
document.getElementById("newBtn").addEventListener("click", () => {
  localStorage.removeItem(STORAGE_KEY);
  stopPolling();
  document.getElementById("statusCard").classList.add("hidden");
  document.getElementById("joinCard").classList.remove("hidden");
  loadOrg();
});

function resetView() {
  renderedMsgCount = 0;
  lastStatus = null;
  document.getElementById("feed").innerHTML = "";
}

/* ---- render the ticket status + bot feed --------------------------------- */
function render(t) {
  document.getElementById("joinCard").classList.add("hidden");
  document.getElementById("statusCard").classList.remove("hidden");

  document.getElementById("ticketNumber").innerHTML = `#${t.ticket_number}<small>${t.service}</small>`;
  const badge = document.getElementById("statusBadge");
  badge.textContent = t.status;
  badge.className = "badge " + t.status;

  const waiting = t.status === "waiting";
  animateCount(document.getElementById("positionVal"), waiting ? t.position : NaN);
  document.getElementById("nowServingVal").textContent = t.now_serving != null ? "#" + t.now_serving : "—";
  animateCount(document.getElementById("waitVal"), waiting ? t.estimated_wait_minutes : NaN);

  // Append only new bot messages (no flicker on the 3s refresh).
  const feed = document.getElementById("feed");
  if (t.messages.length < renderedMsgCount) { feed.innerHTML = ""; renderedMsgCount = 0; }
  for (let i = renderedMsgCount; i < t.messages.length; i++) {
    const m = t.messages[i];
    const div = document.createElement("div");
    div.className = "msg " + m.kind;
    div.innerHTML = `<div class="avatar">${BOT_SVG}</div>
      <div><div class="bubble">${m.message}</div><div class="time">${fmtTime(m.created_at)}</div></div>`;
    feed.appendChild(div);
  }
  renderedMsgCount = t.messages.length;
  feed.scrollTop = feed.scrollHeight;

  // Celebrate the moment it becomes "your turn".
  if (t.status === "serving" && lastStatus && lastStatus !== "serving") celebrate();
  lastStatus = t.status;

  const cancelBtn = document.getElementById("cancelBtn");
  if (TERMINAL_STATUSES.has(t.status)) {
    cancelBtn.disabled = true;
    localStorage.removeItem(STORAGE_KEY);
    stopPolling();
  } else {
    cancelBtn.disabled = false;
  }
}

/* ---- polling ------------------------------------------------------------- */
async function refresh() {
  const id = localStorage.getItem(STORAGE_KEY);
  if (!id) return stopPolling();
  try {
    render(await api(`/api/queue/ticket/${id}`));
  } catch {
    // ticket gone / server reset — return to the join form
    localStorage.removeItem(STORAGE_KEY);
    stopPolling();
    document.getElementById("statusCard").classList.add("hidden");
    document.getElementById("joinCard").classList.remove("hidden");
  }
}
function startPolling() { stopPolling(); pollTimer = setInterval(refresh, 3000); }
function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

/* ---- boot ---------------------------------------------------------------- */
(async function init() {
  await loadOrg();
  if (localStorage.getItem(STORAGE_KEY)) {
    await refresh();
    if (localStorage.getItem(STORAGE_KEY)) startPolling();
  }
})();
