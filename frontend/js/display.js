const slug = decodeURIComponent(window.location.pathname.split("/display/")[1] || "").replace(/\/$/, "");
const POLL_MS = 3000;

let lastSig = "";
let lastServing = new Map();
let voiceEnabled = false;
let latestData = null;

const orgEl = document.getElementById("displayOrg");
const gridEl = document.getElementById("displayGrid");
const heroTicketEl = document.getElementById("heroTicket");
const heroServiceEl = document.getElementById("heroService");
const heroNoteEl = document.getElementById("heroNote");
const clockEl = document.getElementById("clock");
const voiceBtn = document.getElementById("voiceBtn");

async function api(path) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

function fmtTicket(n) {
  return n == null ? "--" : `#${n}`;
}

function updateClock() {
  clockEl.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function speakCall(service, ticket) {
  if (!voiceEnabled || ticket == null || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const msg = new SpeechSynthesisUtterance(`Ticket number ${ticket}, please proceed to ${service}.`);
  msg.rate = 0.92;
  msg.volume = 1;
  window.speechSynthesis.speak(msg);
}

function render(data) {
  latestData = data;
  orgEl.textContent = data.name;
  document.title = `${data.name} - Reception Display`;
  const activeCalls = data.services.filter((s) => s.now_serving != null);
  const hero = activeCalls[0];
  heroTicketEl.textContent = fmtTicket(hero?.now_serving);
  heroServiceEl.textContent = hero ? hero.name : "Waiting for the next call";
  heroNoteEl.textContent = hero ? "Please proceed when your ticket is shown." : "Keep this screen open in the reception area.";
  gridEl.innerHTML = data.services.length
    ? data.services.map(serviceCard).join("")
    : `<div class="display-empty">No services are set up yet.</div>`;
  for (const s of data.services) {
    const previous = lastServing.get(s.id);
    if (previous !== undefined && previous !== s.now_serving && s.now_serving != null) {
      speakCall(s.name, s.now_serving);
    }
    lastServing.set(s.id, s.now_serving);
  }
}

function serviceCard(s) {
  const next = s.next_tickets.length
    ? s.next_tickets.map((n) => `<span>${fmtTicket(n)}</span>`).join("")
    : `<em>No one waiting</em>`;
  return `
    <article class="display-card ${s.status}">
      <div class="display-card-top">
        <h2>${s.name}</h2>
        <span class="badge ${s.status}">${s.status}</span>
      </div>
      <div class="display-card-ticket">${fmtTicket(s.now_serving)}</div>
      <p class="display-card-label">Now serving</p>
      <div class="display-next">
        <strong>Next</strong>
        <div>${next}</div>
      </div>
    </article>`;
}

async function refresh() {
  try {
    const data = await api(`/api/public/display/${encodeURIComponent(slug)}`);
    const sig = JSON.stringify(data);
    if (sig !== lastSig) {
      lastSig = sig;
      render(data);
    }
  } catch {
    document.getElementById("displayApp").classList.add("hidden");
    document.getElementById("displayMissing").classList.remove("hidden");
  }
}

voiceBtn.addEventListener("click", () => {
  voiceEnabled = !voiceEnabled;
  voiceBtn.textContent = voiceEnabled ? "Voice on" : "Enable voice";
  voiceBtn.classList.toggle("on", voiceEnabled);
  if (voiceEnabled && "speechSynthesis" in window) {
    window.speechSynthesis.speak(new SpeechSynthesisUtterance("Voice announcements are on."));
    const current = latestData?.services?.find((s) => s.now_serving != null);
    if (current) {
      setTimeout(() => speakCall(current.name, current.now_serving), 900);
    }
  }
});

updateClock();
setInterval(updateClock, 1000);
refresh();
setInterval(refresh, POLL_MS);
