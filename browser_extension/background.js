let ws = null;
let reconnectTimer = null;
let authFailed = false;
let connecting = false;
let connectionGeneration = 0;

async function getToken() {
  const data = await chrome.storage.local.get("bluelyToken");
  return typeof data.bluelyToken === "string" ? data.bluelyToken.trim() : "";
}

function setBadge(text, color) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

// This function is serialized by Chrome and runs in MAIN, where React's DOM
// expandos exist. Content scripts run in an isolated world and cannot see them.
function readReactMetadata(selector) {
  const element = document.querySelector(selector);
  if (!element) return {};
  const key = Object.keys(element).find(k => k.startsWith("__reactFiber$"));
  if (!key) return {};
  let fiber = element[key];
  const names = [];
  let source = null;
  for (let depth = 0; fiber && depth < 30; depth++) {
    const type = fiber.type;
    const name = type?.displayName || type?.name || type?.render?.displayName || type?.render?.name;
    if (name && !names.includes(name)) names.unshift(name);
    if (!source && fiber._debugSource?.fileName) {
      const debug = fiber._debugSource;
      source = {fileName: debug.fileName, lineNumber: debug.lineNumber, columnNumber: debug.columnNumber};
    }
    fiber = fiber._debugOwner || fiber.return;
  }
  return {reactComponents: names.join(" > "), reactSource: source};
}

function connect() {
  if (connecting || ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;
  const generation = ++connectionGeneration;
  connecting = true;

  getToken().then((token) => {
    if (generation !== connectionGeneration) return;
    if (!token) {
      setBadge("KEY?", "#F59E0B");
      return; // no token yet — storage.onChanged triggers connect once the popup saves one
    }
    authFailed = false;
    const socket = new WebSocket("ws://127.0.0.1:5002");
    ws = socket;
    function send(message) {
      if (ws === socket && socket.readyState === WebSocket.OPEN) {
        socket.send(message);
      }
    }

    socket.onopen = () => {
      send(JSON.stringify({ type: "auth", token }));
    };

    socket.onmessage = async (event) => {
      if (ws !== socket) return;
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        console.error("[Bluely Bridge] Bad message:", e);
        return;
      }
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "auth_ok") {
        setBadge("ON", "#22C55E");
        return;
      }
      if (msg.type === "auth_error") {
        authFailed = true;
        setBadge("AUTH", "#EF4444");
        try {
          socket.close();
        } catch (e) {}
        return;
      }
      if (msg.type === "inspect") {
        try {
        const tabs = await chrome.tabs.query({
          active: true,
          currentWindow: true,
        });
        if (!tabs.length) {
          send(
            JSON.stringify({
              type: "inspect_result",
              id: msg.id,
              error: "No active tab",
            })
          );
          return;
        }
          const result = await chrome.tabs.sendMessage(tabs[0].id, msg);
          let react = {};
          if (result?.selector && !result.error) {
            try {
              const frames = await chrome.scripting.executeScript({
                target: {tabId: tabs[0].id}, world: "MAIN",
                func: readReactMetadata, args: [result.selector],
              });
              react = frames[0]?.result || {};
            } catch (error) {
              console.debug("[Bluely Bridge] React metadata unavailable:", error);
            }
          }
          send(
            JSON.stringify({
              type: "inspect_result",
              id: msg.id,
              ...(result?.error ? { error: result.error } : {...result, ...react}),
            })
          );
        } catch (e) {
          send(
            JSON.stringify({
              type: "inspect_result",
              id: msg.id,
              error: "Content script not loaded: " + e.message,
            })
          );
        }
      }
    };

    socket.onclose = () => {
      if (ws !== socket) return;
      ws = null;
      if (authFailed) {
        setBadge("AUTH", "#EF4444"); // wrong token — wait for the user to fix it
        return;
      }
      setBadge("OFF", "#EF4444");
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    };

    socket.onerror = () => {
      try {
        socket.close();
      } catch (e) {}
    };
  }).catch((error) => {
    if (generation !== connectionGeneration) return;
    console.error("[Bluely Bridge] Token read failed:", error);
    setBadge("ERR", "#EF4444");
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 3000);
  }).finally(() => {
    if (generation === connectionGeneration) connecting = false;
  });
}

// Reconnect whenever the user saves or clears the token in the popup.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.bluelyToken) {
    connectionGeneration++;
    connecting = false;
    const previous = ws;
    ws = null;
    if (previous) {
      try {
        previous.close();
      } catch (e) {}
    }
    clearTimeout(reconnectTimer);
    connect();
  }
});

connect();
