// Arrow Annotate — desktop bridge (MV3 service worker).
//
// Connects to the local WebSocket bridge, authenticates with the per-install
// bearer token, and forwards DOM inspection requests from the desktop app.
// Service workers are suspended by Chrome; this file must behave correctly
// when it is re-evaluated from scratch after every suspension.

const WS_URL_DEFAULT = "ws://127.0.0.1:5002";
const AUTH_TIMEOUT_MS = 10000;
const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 30000;

// Connection states surfaced in the popup.
const STATE = {
  NOT_CONFIGURED: "not_configured",
  DISCONNECTED: "disconnected",
  CONNECTING: "connecting",
  AUTHENTICATING: "authenticating",
  CONNECTED: "connected",
  AUTH_FAILED: "auth_failed",
  SERVER_UNAVAILABLE: "server_unavailable",
};

let ws = null;
let reconnectTimer = null;
let authTimer = null;
let backoffAttempt = 0;
let currentState = STATE.DISCONNECTED;
let stoppedByUser = false;

// The bridge URL must be a ws:// connection to a loopback host. Anything
// else (typo, malicious storage write) falls back to the default so the
// bearer token can never be sent off this machine.
function sanitizeWsUrl(raw) {
  const value = (raw || "").trim();
  if (!value) return WS_URL_DEFAULT;
  let url;
  try {
    url = new URL(value);
  } catch (e) {
    return WS_URL_DEFAULT;
  }
  const loopback = url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "[::1]";
  if (url.protocol !== "ws:" || !loopback || !url.port) return WS_URL_DEFAULT;
  return `ws://${url.hostname}:${url.port}`;
}

async function getStored() {
  // Migrate the legacy key from older versions of the extension.
  const data = await chrome.storage.local.get(["arrowToken", "bluelyToken", "arrowWsUrl"]);
  const token = (data.arrowToken || data.bluelyToken || "").trim();
  const wsUrl = sanitizeWsUrl(data.arrowWsUrl);
  if (!data.arrowToken && data.bluelyToken) {
    chrome.storage.local.set({ arrowToken: data.bluelyToken });
  }
  return { token, wsUrl };
}

function setBadge(text, color) {
  try {
    chrome.action.setBadgeText({ text });
    chrome.action.setBadgeBackgroundColor({ color });
  } catch (e) {
    // Action API can be unavailable during very early startup; ignore.
  }
}

function setState(state, detail) {
  currentState = state;
  const payload = { state, detail: detail || "", at: Date.now() };
  setBadge(badgeFor(state), badgeColor(state));
  chrome.storage.local.set({ arrowConnState: payload }).catch(() => {});
  // Best-effort push to an open popup.
  try {
    chrome.runtime.sendMessage({ type: "conn_state", ...payload }).catch(() => {});
  } catch (e) {
    // No listener — popup closed. Storage already holds the state.
  }
}

function badgeFor(state) {
  switch (state) {
    case STATE.CONNECTED:
      return "ON";
    case STATE.AUTHENTICATING:
      return "…";
    case STATE.CONNECTING:
      return "···";
    case STATE.AUTH_FAILED:
      return "KEY?";
    case STATE.SERVER_UNAVAILABLE:
      return "OFF";
    case STATE.NOT_CONFIGURED:
      return "SET";
    default:
      return "";
  }
}

function badgeColor(state) {
  switch (state) {
    case STATE.CONNECTED:
      return "#22C55E";
    case STATE.AUTH_FAILED:
      return "#F59E0B";
    case STATE.AUTHENTICATING:
    case STATE.CONNECTING:
      return "#3B82F6";
    default:
      return "#EF4444";
  }
}

function clearTimers() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (authTimer != null) {
    clearTimeout(authTimer);
    authTimer = null;
  }
}

function scheduleReconnect(state, detail) {
  clearTimers();
  setState(state, detail);
  if (stoppedByUser) return;
  // Capped exponential backoff with ±25% jitter so many clients (and the
  // service worker's own restarts) do not hammer the local server in lockstep.
  const exp = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * Math.pow(2, backoffAttempt));
  const jitter = exp * 0.25 * (Math.random() * 2 - 1);
  const delay = Math.max(BACKOFF_BASE_MS / 2, Math.round(exp + jitter));
  backoffAttempt += 1;
  reconnectTimer = setTimeout(connect, delay);
}

function teardownSocket() {
  if (authTimer != null) {
    clearTimeout(authTimer);
    authTimer = null;
  }
  if (!ws) return;
  const socket = ws;
  ws = null;
  socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
  try {
    socket.close();
  } catch (e) {
    // Already closed.
  }
}

async function connect() {
  if (stoppedByUser) return;
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return; // duplicate-connection guard
  }

  const { token, wsUrl } = await getStored();
  if (!token) {
    setState(STATE.NOT_CONFIGURED, "Open the popup and paste the local token.");
    return;
  }

  setState(STATE.CONNECTING, wsUrl);
  let socket;
  try {
    socket = new WebSocket(wsUrl);
  } catch (e) {
    scheduleReconnect(STATE.SERVER_UNAVAILABLE, String(e && e.message ? e.message : e));
    return;
  }
  ws = socket;

  socket.onopen = () => {
    if (ws !== socket) return;
    setState(STATE.AUTHENTICATING, "Verifying token…");
    try {
      socket.send(JSON.stringify({ type: "auth", token }));
    } catch (e) {
      scheduleReconnect(STATE.DISCONNECTED, "Failed to send auth message.");
      return;
    }
    authTimer = setTimeout(() => {
      if (ws === socket && currentState !== STATE.CONNECTED) {
        scheduleReconnect(STATE.DISCONNECTED, "The desktop app did not answer the handshake in time.");
        teardownSocket();
      }
    }, AUTH_TIMEOUT_MS);
  };

  socket.onmessage = (event) => {
    if (ws !== socket) return;
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (e) {
      console.error("[Arrow Bridge] malformed message from desktop:", e);
      return;
    }
    switch (msg.type) {
      case "auth_ok":
        backoffAttempt = 0;
        if (authTimer != null) {
          clearTimeout(authTimer);
          authTimer = null;
        }
        setState(STATE.CONNECTED, "");
        break;
      case "auth_error":
        stoppedByUser = true; // wrong token: wait for the user, do not spin
        setState(STATE.AUTH_FAILED, msg.error || "The desktop app rejected the token.");
        teardownSocket();
        break;
      case "inspect":
        handleInspect(msg, socket);
        break;
      default:
        break;
    }
  };

  socket.onclose = (event) => {
    if (ws !== socket) return;
    ws = null;
    if (authTimer != null) {
      clearTimeout(authTimer);
      authTimer = null;
    }
    if (currentState === STATE.AUTH_FAILED || stoppedByUser) return;
    const unavailable = event && (event.code === 1006 || event.code === 1011);
    scheduleReconnect(
      unavailable ? STATE.SERVER_UNAVAILABLE : STATE.DISCONNECTED,
      unavailable ? "Desktop app is not running or the bridge port is closed." : "Connection closed."
    );
  };

  socket.onerror = () => {
    // onclose follows and performs the backoff; nothing to do here.
  };
}

async function handleInspect(msg, socket) {
  const send = (payload) => {
    if (socket !== ws || socket.readyState !== WebSocket.OPEN) return;
    try {
      socket.send(JSON.stringify(payload));
    } catch (e) {
      console.error("[Arrow Bridge] failed to reply:", e);
    }
  };

  let tabs = [];
  try {
    tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  } catch (e) {
    send({ type: "inspect_result", id: msg.id, error: "Cannot query tabs: " + e.message });
    return;
  }
  if (!tabs.length) {
    send({ type: "inspect_result", id: msg.id, error: "No active tab" });
    return;
  }

  // The content script is no longer declared for all sites: it is injected
  // on demand, only when the desktop app asks to inspect the active tab.
  let result = null;
  try {
    result = await chrome.tabs.sendMessage(tabs[0].id, msg);
  } catch (e) {
    // Not injected yet (or the page was reloaded) — inject and retry once.
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tabs[0].id },
        files: ["content.js"],
      });
      result = await chrome.tabs.sendMessage(tabs[0].id, msg);
    } catch (injectErr) {
      const text = String(injectErr && injectErr.message ? injectErr.message : injectErr);
      // Check the permission case first: Chrome phrases missing host access
      // as "Cannot access contents of the page. Extension manifest must
      // request permission…", which would otherwise match the restricted test.
      const noPermission = /manifest must request permission|host permission/i.test(text);
      const restricted = /Cannot access|restricted|chrome:\/\//i.test(text);
      send({
        type: "inspect_result",
        id: msg.id,
        error: noPermission
          ? "Page access not granted — open the extension popup and allow site access for this tab."
          : restricted
            ? "This page does not allow extensions (chrome:// or web store)."
            : "Content script not loaded: " + text,
      });
      return;
    }
  }

  if (chrome.runtime.lastError) {
    send({ type: "inspect_result", id: msg.id, error: chrome.runtime.lastError.message });
    return;
  }
  send({
    type: "inspect_result",
    id: msg.id,
    ...(result && result.error ? { error: result.error } : result || {}),
  });
}

// Reconnect whenever the user saves, clears or migrates the token.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.arrowToken || changes.bluelyToken || changes.arrowWsUrl) {
    stoppedByUser = false;
    backoffAttempt = 0;
    teardownSocket();
    clearTimers();
    connect();
  }
});

// Popup can request an immediate status refresh or reconnect.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "reconnect") {
    stoppedByUser = false;
    backoffAttempt = 0;
    teardownSocket();
    clearTimers();
    connect();
    sendResponse({ ok: true });
    return true;
  }
  if (msg && msg.type === "get_state") {
    sendResponse({ state: currentState });
    return true;
  }
  return false;
});

// Re-evaluated after every service-worker suspension: reconnect immediately
// when a token exists, otherwise surface NOT_CONFIGURED.
getStored().then(({ token }) => {
  if (!token) {
    setState(STATE.NOT_CONFIGURED, "Open the popup and paste the local token.");
    return;
  }
  connect();
});
