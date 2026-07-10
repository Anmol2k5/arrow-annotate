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
      if (msg.type === "inspect" || msg.type === "start_annotation_mode") {
        const tabs = await chrome.tabs.query({
          active: true,
          currentWindow: true,
        });
        if (!tabs.length) {
          ws.send(
            JSON.stringify({
              type: msg.type === "inspect" ? "inspect_result" : "annotation_result",
              id: msg.id,
              error: "No active tab",
            })
          );
          return;
        }

        try {
          // Forward message to content script
          const result = await chrome.tabs.sendMessage(tabs[0].id, msg);
          
          if (msg.type === "start_annotation_mode" && result && !result.error) {
            // Capture the tab natively as a clean base64 screenshot
            chrome.tabs.captureVisibleTab(null, { format: "png" }, (dataUrl) => {
              const base64Data = dataUrl ? dataUrl.split(",")[1] : "";
              
              const response = {
                protocolVersion: 1,
                requestId: msg.id,
                captureId: msg.captureId || "",
                status: "ok",
                tab: {
                  id: tabs[0].id,
                  title: tabs[0].title || "",
                  url: tabs[0].url || "",
                  screenshot: base64Data
                },
                viewport: result.viewport || {},
                element: result.element || {},
                page: result.page || {}
              };

              ws.send(
                JSON.stringify({
                  type: "annotation_result",
                  id: msg.id,
                  ...response
                })
              );
            });
          } else {
            ws.send(
              JSON.stringify({
                type: msg.type === "inspect" ? "inspect_result" : "annotation_result",
                id: msg.id,
                ...(result?.error ? { error: result.error } : result),
              })
            );
          }
        } catch (e) {
          ws.send(
            JSON.stringify({
              type: msg.type === "inspect" ? "inspect_result" : "annotation_result",
              id: msg.id,
              error: "Content script failure: " + e.message,
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
