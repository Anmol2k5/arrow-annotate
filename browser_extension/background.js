let ws = null;
let reconnectTimer = null;

function connect() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;

  ws = new WebSocket("ws://127.0.0.1:5002");

  ws.onopen = () => {
    console.log("[Bluely Bridge] Connected");
    chrome.action.setBadgeText({ text: "ON" });
    chrome.action.setBadgeBackgroundColor({ color: "#22C55E" });
  };

  ws.onmessage = async (event) => {
    try {
      const msg = JSON.parse(event.data);
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
    } catch (e) {
      console.error("[Bluely Bridge] Message error:", e);
    }
  };

  ws.onclose = () => {
    console.log("[Bluely Bridge] Disconnected");
    chrome.action.setBadgeText({ text: "OFF" });
    chrome.action.setBadgeBackgroundColor({ color: "#EF4444" });
    reconnectTimer = setTimeout(connect, 3000);
  };

  ws.onerror = () => {
    ws?.close();
  };
}

connect();
