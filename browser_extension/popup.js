const tokenInput = document.getElementById("token");
const saveBtn = document.getElementById("save");
const loadBtn = document.getElementById("load");
const fileInput = document.getElementById("file");
const statusEl = document.getElementById("status");

async function currentToken() {
  const data = await chrome.storage.local.get("bluelyToken");
  return data.bluelyToken || "";
}

currentToken().then((token) => {
  tokenInput.value = token;
  if (token) {
    statusEl.textContent = "Token configured — the bridge reconnects automatically.";
  } else {
    statusEl.textContent = "No token yet. Paste it or load it from the token file.";
  }
});

saveBtn.addEventListener("click", async () => {
  const token = tokenInput.value.trim();
  await chrome.storage.local.set({ bluelyToken: token });
  statusEl.textContent = token ? "Token saved — reconnecting…" : "Token cleared.";
});

loadBtn.addEventListener("click", () => {
  fileInput.value = "";
  fileInput.click();
});

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;
  const text = await file.text();
  const token = text.trim();
  tokenInput.value = token;
  if (token) {
    await chrome.storage.local.set({ bluelyToken: token });
    statusEl.textContent = "Token loaded from file — reconnecting…";
  } else {
    statusEl.textContent = "That file was empty — expected the token in ~/.arrow/token.";
  }
});
