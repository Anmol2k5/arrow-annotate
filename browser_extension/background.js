let ws = null;
let reconnectTimer = null;
let authFailed = false;

async function getToken() {
  const data = await chrome.storage.local.get("bluelyToken");
  return (data.bluelyToken || "").trim();
}

function setBadge(text, color) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

function connect() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;

  getToken().then((token) => {
    if (!token) {
      setBadge("KEY?", "#F59E0B");
      return; // no token yet — storage.onChanged triggers connect once the popup saves one
    }
    authFailed = false;
    ws = new WebSocket("ws://127.0.0.1:5002");

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token }));
    };

    ws.onmessage = async (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        console.error("[Bluely Bridge] Bad message:", e);
        return;
      }
      if (msg.type === "auth_ok") {
        setBadge("ON", "#22C55E");
        return;
      }
      if (msg.type === "auth_error") {
        authFailed = true;
        setBadge("AUTH", "#EF4444");
        try {
          ws?.close();
        } catch (e) {}
        return;
      }
      if (msg.type === "inspect") {
        const tabs = await chrome.tabs.query({
          active: true,
          currentWindow: true,
        });
        if (!tabs.length) {
          ws.send(
            JSON.stringify({
              type: "inspect_result",
              id: msg.id,
              error: "No active tab",
            })
          );
          return;
        }
        try {
          const result = await chrome.tabs.sendMessage(tabs[0].id, msg);
          ws.send(
            JSON.stringify({
              type: "inspect_result",
              id: msg.id,
              ...(result?.error ? { error: result.error } : result),
            })
          );
        } catch (e) {
          ws.send(
            JSON.stringify({
              type: "inspect_result",
              id: msg.id,
              error: "Content script not loaded: " + e.message,
            })
          );
        }
      }
    };

    ws.onclose = () => {
      if (authFailed) {
        setBadge("AUTH", "#EF4444"); // wrong token — wait for the user to fix it
        return;
      }
      setBadge("OFF", "#EF4444");
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      try {
        ws?.close();
      } catch (e) {}
    };
  });
}

// Reconnect whenever the user saves or clears the token in the popup.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.bluelyToken) {
    if (ws) {
      try {
        ws.close();
      } catch (e) {}
      ws = null;
    }
    clearTimeout(reconnectTimer);
    connect();
  }
});

connect();
