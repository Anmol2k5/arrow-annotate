// Arrow Annotate — extension popup.
// Reflects the *actual* WebSocket state reported by the service worker;
// saving a token is not the same as being connected.

const tokenInput = document.getElementById("token");
const wsUrlInput = document.getElementById("wsurl");
const saveBtn = document.getElementById("save");
const loadBtn = document.getElementById("load");
const retryBtn = document.getElementById("retry");
const allowBtn = document.getElementById("allow");
const fileInput = document.getElementById("file");
const statusEl = document.getElementById("status");
const statusText = document.getElementById("statusText");
const connDot = document.getElementById("connDot");

const STATE_COPY = {
  not_configured: ["No token configured yet.", "warn", ""],
  disconnected: ["Disconnected — retrying…", "warn", ""],
  connecting: ["Connecting to the desktop app…", "", "busy"],
  authenticating: ["Connected — verifying token…", "", "busy"],
  connected: ["Connected to Arrow Annotate.", "ok", "on"],
  auth_failed: ["Token rejected. Check the token file and save again.", "err", "bad"],
  server_unavailable: ["Desktop app unreachable. Start Arrow Annotate, then retry.", "err", "bad"],
};

let lastState = null;

function render(state, detail) {
  lastState = state;
  const [text, cls, dot] = STATE_COPY[state] || [`State: ${state}`, "warn", ""];
  statusText.textContent = detail && state !== "connected" ? `${text} ${detail}` : text;
  statusEl.className = cls;
  connDot.className = `conn ${dot}`;
}

async function currentToken() {
  const data = await chrome.storage.local.get(["arrowToken", "bluelyToken"]);
  return data.arrowToken || data.bluelyToken || "";
}

// Only loopback ws:// addresses are accepted; mirrors the service worker's
// sanitizer so the user gets feedback here instead of a silent fallback.
function validWsUrl(value) {
  if (!value) return true; // empty = default bridge URL
  try {
    const url = new URL(value);
    const loopback = url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "[::1]";
    return url.protocol === "ws:" && loopback && !!url.port;
  } catch (e) {
    return false;
  }
}

async function refreshState() {
  try {
    const resp = await chrome.runtime.sendMessage({ type: "get_state" });
    if (resp && resp.state) {
      render(resp.state);
      return;
    }
  } catch (e) {
    // Service worker may be asleep and waking; fall through to storage.
  }
  const data = await chrome.storage.local.get("arrowConnState");
  if (data.arrowConnState) render(data.arrowConnState.state, data.arrowConnState.detail);
}

async function init() {
  const token = await currentToken();
  tokenInput.value = token;
  const stored = await chrome.storage.local.get("arrowWsUrl");
  wsUrlInput.value = (stored.arrowWsUrl || "").trim();
  if (!token) {
    render("not_configured");
  } else {
    await refreshState();
  }
  await refreshAllowState();
}

// Live updates from the service worker.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "conn_state") render(msg.state, msg.detail);
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.arrowConnState && changes.arrowConnState.newValue) {
    const v = changes.arrowConnState.newValue;
    render(v.state, v.detail);
  }
});

saveBtn.addEventListener("click", async () => {
  const token = tokenInput.value.trim();
  const wsUrl = wsUrlInput.value.trim();
  if (!validWsUrl(wsUrl)) {
    statusText.textContent = "Bridge URL must be a loopback ws:// address (e.g. ws://127.0.0.1:5002).";
    statusEl.className = "err";
    return;
  }
  if (!token) {
    await chrome.storage.local.remove(["arrowToken", "bluelyToken"]);
    render("not_configured");
    return;
  }
  statusText.textContent = "Token saved — connecting…";
  statusEl.className = "";
  // Empty wsUrl clears the override — the sanitizer treats it as the default.
  await chrome.storage.local.set({ arrowToken: token, arrowWsUrl: wsUrl });
  // The service worker reacts to the storage change and connects; the status
  // line updates from its real state messages (never claims success early).
  chrome.runtime.sendMessage({ type: "reconnect" }).catch(() => {});
});

retryBtn.addEventListener("click", () => {
  statusText.textContent = "Reconnecting…";
  statusEl.className = "";
  chrome.runtime.sendMessage({ type: "reconnect" }).catch(() => refreshState());
});

// On-demand page access: the content script is only injected when the desktop
// app inspects, and only succeeds on origins the user has allowed here.
async function activeOrigin() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) return null;
    const url = new URL(tab.url);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return `${url.protocol}//${url.host}/*`;
  } catch (e) {
    return null;
  }
}

async function refreshAllowState() {
  const origin = await activeOrigin();
  if (!origin) {
    allowBtn.textContent = "Allow access to this site";
    allowBtn.disabled = true;
    allowBtn.title = "Open a normal http(s) tab to allow site access.";
    return;
  }
  try {
    const granted = await chrome.permissions.contains({ origins: [origin] });
    allowBtn.textContent = granted ? "✓ Access allowed for this site" : "Allow access to this site";
    allowBtn.disabled = granted;
    allowBtn.title = granted ? "" : `Lets Arrow inspect this site when the desktop app asks.`;
  } catch (e) {
    allowBtn.disabled = false;
  }
}

allowBtn.addEventListener("click", async () => {
  const origin = await activeOrigin();
  if (!origin) return;
  try {
    const granted = await chrome.permissions.request({ origins: [origin] });
    await refreshAllowState();
    if (granted) {
      statusText.textContent = "Site access allowed — Arrow can inspect this site.";
      statusEl.className = "ok";
    } else {
      statusText.textContent = "Site access declined — Arrow cannot inspect this site.";
      statusEl.className = "warn";
    }
  } catch (e) {
    statusText.textContent = "Could not request site access: " + (e && e.message ? e.message : e);
    statusEl.className = "err";
  }
});

chrome.permissions && chrome.permissions.onRemoved &&
  chrome.permissions.onRemoved.addListener(() => refreshAllowState());

loadBtn.addEventListener("click", () => {
  fileInput.value = "";
  fileInput.click();
});

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;
  const text = (await file.text()).trim();
  tokenInput.value = text;
  if (text) {
    await chrome.storage.local.set({ arrowToken: text });
    statusText.textContent = "Token loaded — connecting…";
    statusEl.className = "";
    chrome.runtime.sendMessage({ type: "reconnect" }).catch(() => {});
  } else {
    statusText.textContent = "That file was empty — expected the token in ~/.arrow/token.";
    statusEl.className = "err";
  }
});

init();
