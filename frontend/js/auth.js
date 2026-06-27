// Landing page: sign up / log in. On success, store the token and go to the dashboard.

const TOKEN_KEY = "queuebot.token";

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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

// If already logged in, skip straight to the dashboard.
if (localStorage.getItem(TOKEN_KEY)) {
  window.location.href = "/dashboard.html";
}

// ---- tab toggle ----
const signupForm = document.getElementById("signupForm");
const loginForm = document.getElementById("loginForm");
const tabSignup = document.getElementById("tabSignup");
const tabLogin = document.getElementById("tabLogin");

function showSignup(yes) {
  tabSignup.classList.toggle("active", yes);
  tabLogin.classList.toggle("active", !yes);
  signupForm.classList.toggle("hidden", !yes);
  loginForm.classList.toggle("hidden", yes);
}
tabSignup.addEventListener("click", () => showSignup(true));
tabLogin.addEventListener("click", () => showSignup(false));

function succeed(data) {
  localStorage.setItem(TOKEN_KEY, data.token);
  window.location.href = "/dashboard.html";
}

// ---- signup ----
signupForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = document.getElementById("su_error");
  err.textContent = "";
  const btn = ev.target.querySelector("button");
  btn.disabled = true;
  try {
    const data = await api("/api/auth/signup", {
      name: document.getElementById("su_name").value,
      email: document.getElementById("su_email").value,
      password: document.getElementById("su_password").value,
    });
    succeed(data);
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

// ---- login ----
loginForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = document.getElementById("li_error");
  err.textContent = "";
  const btn = ev.target.querySelector("button");
  btn.disabled = true;
  try {
    const data = await api("/api/auth/login", {
      email: document.getElementById("li_email").value,
      password: document.getElementById("li_password").value,
    });
    succeed(data);
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});
