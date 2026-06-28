const TOKEN_KEY = "queuebot.token";
const token = localStorage.getItem(TOKEN_KEY);
if (!token) window.location.href = "/";

let pollTimer = null;
let lastBoardSig = null;

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) },
  });
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/";
    throw new Error("Session expired");
  }
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

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function animateCount(el, target) {
  const dur = 700, t0 = performance.now();
  (function step(now) {
    const p = Math.min((now - t0) / dur, 1);
    el.textContent = Math.round((1 - Math.pow(1 - p, 3)) * target);
    if (p < 1) requestAnimationFrame(step);
  })(performance.now());
}

const CHECK = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>`;

async function loadAccount() {
  const me = await api("/api/auth/me");
  document.getElementById("orgName").textContent = me.name;
  const link = `${window.location.origin}/q/${me.slug}`;
  document.getElementById("shareLink").value = link;
  document.getElementById("copyBtn").onclick = async () => {
    try { await navigator.clipboard.writeText(link); toast("Link copied!"); }
    catch { document.getElementById("shareLink").select(); toast("Press Ctrl+C to copy"); }
  };
  document.getElementById("openBtn").onclick = () => window.open(link, "_blank");
}

document.getElementById("logoutBtn").onclick = async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } catch {}
  localStorage.removeItem(TOKEN_KEY);
  window.location.href = "/";
};

const PANEL_META = {
  queue: { title: "Queue", sub: "Call customers, mark no-shows, and keep each line moving." },
  services: { title: "Services", sub: "Choose services and control whether each queue is open, paused, or closed." },
  report: { title: "Report", sub: "Today's activity at a glance." },
};

function switchTab(name) {
  document.querySelectorAll(".side-nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + name));
  document.getElementById("panelTitle").textContent = PANEL_META[name].title;
  document.getElementById("panelSub").textContent = PANEL_META[name].sub;
  if (name === "services") loadServices();
  if (name === "report") loadReport();
}

document.querySelectorAll(".side-nav button").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

function statusLabel(status) {
  return status === "open" ? "Open" : status === "paused" ? "Paused" : "Closed";
}

function serviceCard(s) {
  const status = s.status || "open";
  const ns = s.now_serving
    ? `<div class="now-serving"><span class="ring"></span><div class="num">#${s.now_serving.ticket_number}</div><div class="nm">${s.now_serving.name}</div></div>`
    : `<div class="now-serving idle"><div class="num">-</div><div class="nm">No one at the counter</div></div>`;
  const list = s.waiting.length
    ? s.waiting.map((w) => `<li><span><span class="tn">#${w.ticket_number}</span> &nbsp; ${w.name}</span><span class="muted">${fmtTime(w.created_at)}</span></li>`).join("")
    : `<li class="empty">Queue is empty</li>`;
  return `
    <section class="card service-card hoverable">
      <div class="row-between" style="margin-bottom:14px;">
        <h2>${s.name}</h2>
        <span class="badge ${status}">${statusLabel(status)}</span>
      </div>
      <p class="muted" style="margin:-8px 0 12px;">${s.waiting_count} waiting - ~${s.avg_minutes} min</p>
      ${ns}
      <ul class="waiting-list">${list}</ul>
      <div class="action-row">
        <button class="btn" data-service="${s.id}" ${status === "closed" || (s.waiting_count === 0 && !s.now_serving) ? "disabled" : ""}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          Call next
        </button>
        <button class="btn danger" data-noshow="${s.id}" ${!s.now_serving ? "disabled" : ""}>No-show</button>
      </div>
    </section>`;
}

async function loadBoard() {
  try {
    const services = await api("/api/owner/overview");
    const sig = JSON.stringify(services);
    if (sig === lastBoardSig) return;
    lastBoardSig = sig;

    const board = document.getElementById("board");
    if (!services.length) {
      board.innerHTML = `
        <div class="card empty-state" style="grid-column:1/-1;">
          <div class="big-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h18M3 12h18M3 17h18"/></svg></div>
          <h2>No services yet</h2>
          <p class="muted" style="max-width:380px;margin:6px auto 0;">Set up which services your customers can queue for. Pick a template or add your own.</p>
          <button class="btn" id="goSetup" style="width:auto;margin:18px auto 0;">Set up services</button>
        </div>`;
      document.getElementById("goSetup").onclick = () => switchTab("services");
      return;
    }
    board.innerHTML = services.map(serviceCard).join("");
    board.querySelectorAll("button[data-service]").forEach((btn) => {
      btn.addEventListener("click", () => callNext(Number(btn.dataset.service)));
    });
    board.querySelectorAll("button[data-noshow]").forEach((btn) => {
      btn.addEventListener("click", () => markNoShow(Number(btn.dataset.noshow)));
    });
  } catch (e) {
    toast(e.message);
  }
}

async function callNext(serviceId) {
  try {
    const r = await api("/api/owner/next", { method: "POST", body: JSON.stringify({ service_id: serviceId }) });
    toast(r.queue_empty
      ? `${r.service}: no one waiting${r.completed ? ` (finished #${r.completed})` : ""}`
      : `${r.service}: now serving #${r.now_serving} - ${r.now_serving_name}`);
    lastBoardSig = null;
    loadBoard();
  } catch (e) { toast(e.message); }
}

async function markNoShow(serviceId) {
  if (!confirm("Mark the current customer as no-show and call the next person?")) return;
  try {
    const r = await api("/api/owner/no-show", { method: "POST", body: JSON.stringify({ service_id: serviceId }) });
    toast(r.queue_empty
      ? `${r.service}: marked #${r.no_show} no-show`
      : `${r.service}: #${r.no_show} no-show; now serving #${r.now_serving}`);
    lastBoardSig = null;
    loadBoard();
  } catch (e) { toast(e.message); }
}

let templates = [];
let activeTemplate = 0;

async function loadTemplates() {
  templates = await api("/api/service-templates");
  const row = document.getElementById("tmplRow");
  row.innerHTML = templates.map((t, i) =>
    `<button class="tmpl-btn ${i === 0 ? "active" : ""}" data-i="${i}">${t.category}</button>`).join("");
  row.querySelectorAll(".tmpl-btn").forEach((b) =>
    b.addEventListener("click", () => { activeTemplate = Number(b.dataset.i); renderChips(); }));
  renderChips();
}

function renderChips() {
  document.querySelectorAll(".tmpl-btn").forEach((b) => b.classList.toggle("active", Number(b.dataset.i) === activeTemplate));
  const chips = document.getElementById("tmplChips");
  const svcs = templates[activeTemplate]?.services || [];
  chips.innerHTML = svcs.map((s) =>
    `<div class="chip sel" data-name="${s.name}" data-min="${s.avg_minutes}">${s.name}<span class="tick">${CHECK}</span></div>`).join("");
  chips.querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => { c.classList.toggle("sel"); updateAddBtn(); }));
  updateAddBtn();
}

function updateAddBtn() {
  const n = document.querySelectorAll("#tmplChips .chip.sel").length;
  const btn = document.getElementById("addSelectedBtn");
  btn.disabled = n === 0;
  btn.textContent = n ? `Add ${n} selected service${n > 1 ? "s" : ""}` : "Add selected services";
}

document.getElementById("addSelectedBtn").addEventListener("click", async () => {
  const items = [...document.querySelectorAll("#tmplChips .chip.sel")].map((c) => ({
    name: c.dataset.name, avg_minutes: Number(c.dataset.min),
  }));
  if (!items.length) return;
  try {
    await api("/api/owner/services/bulk", { method: "POST", body: JSON.stringify({ services: items }) });
    toast(`Added ${items.length} service${items.length > 1 ? "s" : ""}`);
    lastBoardSig = null;
    loadServices();
  } catch (e) { toast(e.message); }
});

async function loadServices() {
  try {
    const services = await api("/api/owner/services");
    document.getElementById("serviceList").innerHTML = services.length
      ? services.map((s) => `
          <div class="svc-row">
            <div><strong>${s.name}</strong> <span class="meta">- ${s.status} - ~${s.avg_minutes} min - ${s.waiting} waiting</span></div>
            <div class="svc-actions">
              <button class="btn small ghost" data-status="${s.id}" data-next="${s.status === "open" ? "paused" : "open"}">${s.status === "open" ? "Pause" : "Open"}</button>
              <button class="btn small ghost" data-status="${s.id}" data-next="closed">Close</button>
              <button class="btn danger small" data-del="${s.id}">Remove</button>
            </div>
          </div>`).join("")
      : `<p class="muted">No services added yet - pick some above to get started.</p>`;
    document.querySelectorAll("button[data-status]").forEach((btn) =>
      btn.addEventListener("click", () => setServiceStatus(Number(btn.dataset.status), btn.dataset.next)));
    document.querySelectorAll("button[data-del]").forEach((btn) =>
      btn.addEventListener("click", () => removeService(Number(btn.dataset.del))));
  } catch (e) { toast(e.message); }
}

async function setServiceStatus(id, status) {
  try {
    await api(`/api/owner/services/${id}/status`, { method: "POST", body: JSON.stringify({ status }) });
    toast(`Service ${status}`);
    loadServices();
    lastBoardSig = null;
    loadBoard();
  } catch (e) { toast(e.message); }
}

async function removeService(id) {
  if (!confirm("Remove this service? Waiting tickets will no longer be shown.")) return;
  try {
    await api(`/api/owner/services/${id}`, { method: "DELETE" });
    toast("Service removed");
    loadServices();
    lastBoardSig = null;
  } catch (e) { toast(e.message); }
}

document.getElementById("addServiceForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await api("/api/owner/services", {
      method: "POST",
      body: JSON.stringify({ name: document.getElementById("svc_name").value, avg_minutes: Number(document.getElementById("svc_min").value) || 5 }),
    });
    document.getElementById("svc_name").value = "";
    toast("Service added");
    loadServices();
    lastBoardSig = null;
  } catch (e) { toast(e.message); }
});

function kpi(value, label, cls = "") {
  return `<div class="kpi ${cls}"><div class="v" data-target="${value}">0</div><div class="l">${label}</div></div>`;
}

async function loadReport() {
  try {
    const r = await api("/api/owner/report");
    document.getElementById("reportDate").textContent = `Activity for ${r.date}`;
    const t = r.totals;
    document.getElementById("kpis").innerHTML = [
      kpi(t.issued, "Issued"), kpi(t.served, "Served", "good"),
      kpi(t.waiting, "Waiting"), kpi(t.serving, "At counter"),
      kpi(t.cancelled, "Cancelled", "bad"), kpi(t.no_show || 0, "No-show", "bad"),
    ].join("");
    document.querySelectorAll("#kpis .v").forEach((el) => animateCount(el, Number(el.dataset.target)));
    document.getElementById("serviceRows").innerHTML = r.per_service.map((s) => `
      <tr><td><strong>${s.service}</strong></td><td>${s.issued}</td><td>${s.served}</td><td>${s.cancelled}</td>
      <td>${s.no_show || 0}</td><td>${s.avg_service_minutes != null ? s.avg_service_minutes + " min" : "-"}</td></tr>`).join("");
  } catch (e) { toast(e.message); }
}

document.getElementById("refreshReport").addEventListener("click", loadReport);

(async function init() {
  await loadAccount();
  await loadTemplates();
  const services = await api("/api/owner/services");
  await loadBoard();
  pollTimer = setInterval(loadBoard, 3000);
  if (!services.length) switchTab("services");
})();
