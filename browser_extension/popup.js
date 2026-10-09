// Arrow Annotate — extension popup.
// Reflects the *actual* WebSocket state reported by the service worker;
// saving a token is not the same as being connected.

const tokenInput = document.getElementById("token");
const saveBtn = document.getElementById("save");
const loadBtn = document.getElementById("load");
const retryBtn = document.getElementById("retry");
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
  if (!token) {
    render("not_configured");
  } else {
    await refreshState();
  }
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
  if (!token) {
    await chrome.storage.local.remove(["arrowToken", "bluelyToken"]);
    render("not_configured");
    return;
  }
  statusText.textContent = "Token saved — connecting…";
  statusEl.className = "";
  await chrome.storage.local.set({ arrowToken: token });
  // The service worker reacts to the storage change and connects; the status
  // line updates from its real state messages (never claims success early).
  chrome.runtime.sendMessage({ type: "reconnect" }).catch(() => {});
});

retryBtn.addEventListener("click", () => {
  statusText.textContent = "Reconnecting…";
  statusEl.className = "";
  chrome.runtime.sendMessage({ type: "reconnect" }).catch(() => refreshState());
});

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
