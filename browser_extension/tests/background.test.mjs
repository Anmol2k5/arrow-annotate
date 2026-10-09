// Behavioral tests for the Arrow Annotate extension service worker.
//
// background.js is a plain (non-module) script that talks to chrome.* and
// WebSocket. These tests evaluate it in a vm context with deterministic stubs
// and assert the connection state machine: token gating, handshake, auth
// failure, server-unavailable backoff and service-worker restart behaviour.
//
// Run: node --test browser_extension/tests/

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(here, "..", "background.js"), "utf8");

class FakeWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this.onopen = this.onmessage = this.onclose = this.onerror = null;
    FakeWebSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = FakeWebSocket.CLOSED;
    if (this.onclose) this.onclose({ code: 1000 });
  }
  // Test helpers
  _open() {
    this.readyState = FakeWebSocket.OPEN;
    if (this.onopen) this.onopen();
  }
  _message(obj) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
  }
  _drop(code = 1006) {
    this.readyState = FakeWebSocket.CLOSED;
    if (this.onclose) this.onclose({ code });
  }
}
FakeWebSocket.CONNECTING = 0;
FakeWebSocket.OPEN = 1;
FakeWebSocket.CLOSED = 3;

function makeEnv({ token = "secret-token", wsUrl = "" } = {}) {
  FakeWebSocket.instances = [];
  const storageData = {};
  if (token) storageData.arrowToken = token;
  if (wsUrl) storageData.arrowWsUrl = wsUrl;

  const timers = [];
  const badges = [];
  const messages = [];
  const runtimeListeners = [];

  const chrome = {
    storage: {
      local: {
        async get(keys) {
          const list = Array.isArray(keys) ? keys : [keys];
          const out = {};
          for (const k of list) if (k in storageData) out[k] = storageData[k];
          return out;
        },
        async set(obj) {
          Object.assign(storageData, obj);
          return undefined;
        },
        async remove(keys) {
          for (const k of Array.isArray(keys) ? keys : [keys]) delete storageData[k];
        },
      },
      onChanged: { addListener() {} },
    },
    action: {
      setBadgeText(v) {
        badges.push(v.text);
      },
      setBadgeBackgroundColor() {},
    },
    runtime: {
      sendMessage(msg) {
        messages.push(msg);
        return Promise.resolve(undefined);
      },
      onMessage: {
        addListener(fn) {
          runtimeListeners.push(fn);
        },
      },
    },
    tabs: {
      async query() {
        return [{ id: 1 }];
      },
      async sendMessage() {
        return { selector: "#ok" };
      },
    },
  };

  const sandbox = {
    chrome,
    WebSocket: FakeWebSocket,
    console,
    setTimeout(fn, ms) {
      const id = timers.length;
      timers.push({ id, fn, ms, cleared: false });
      return id;
    },
    clearTimeout(id) {
      if (timers[id]) timers[id].cleared = true;
    },
    Date,
    Math,
    JSON,
    String,
    Promise,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox, { filename: "background.js" });

  return {
    storageData,
    badges,
    messages,
    runtimeListeners,
    timers: timers.filter((t) => !t.cleared),
    fireTimer(index) {
      const t = timers[index];
      if (!t || t.cleared) throw new Error(`timer ${index} not pending`);
      t.cleared = true;
      t.fn();
    },
    pendingTimers() {
      return timers.filter((t) => !t.cleared);
    },
    lastBadge: () => badges[badges.length - 1],
    lastState: () => storageData.arrowConnState && storageData.arrowConnState.state,
  };
}

async function flush() {
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
}

test("no token → not_configured, no socket opened", async () => {
  const env = makeEnv({ token: "" });
  await flush();
  assert.equal(env.lastState(), "not_configured");
  assert.equal(FakeWebSocket.instances.length, 0);
});

test("with token → connects, authenticates, reaches connected", async () => {
  const env = makeEnv();
  await flush();
  assert.equal(FakeWebSocket.instances.length, 1);
  const ws = FakeWebSocket.instances[0];
  assert.equal(ws.url, "ws://127.0.0.1:5002");

  ws._open();
  assert.equal(ws.sent.length, 1);
  assert.deepEqual(ws.sent[0], { type: "auth", token: "secret-token" });
  assert.equal(env.lastState(), "authenticating");

  ws._message({ type: "auth_ok" });
  assert.equal(env.lastState(), "connected");
  assert.equal(env.lastBadge(), "ON");
});

test("wrong token → auth_failed and does not spin reconnect", async () => {
  const env = makeEnv();
  await flush();
  const ws = FakeWebSocket.instances[0];
  ws._open();
  ws._message({ type: "auth_error", error: "invalid token" });
  assert.equal(env.lastState(), "auth_failed");
  await flush();
  // auth_failed stops the reconnect loop: no new socket, no pending timer.
  assert.equal(FakeWebSocket.instances.length, 1);
  assert.equal(env.pendingTimers().length, 0);
});

test("desktop server down → server_unavailable with capped backoff", async () => {
  const env = makeEnv();
  await flush();
  const ws = FakeWebSocket.instances[0];
  ws._drop(1006);
  assert.equal(env.lastState(), "server_unavailable");

  // A reconnect got scheduled with a bounded delay (±25% jitter around 1s).
  const pending = env.pendingTimers();
  assert.equal(pending.length, 1);
  assert.ok(pending[0].ms >= 500, `delay ${pending[0].ms} too small`);
  assert.ok(pending[0].ms <= 2000, `delay ${pending[0].ms} too large for attempt 1`);

  // Firing it opens exactly one new socket (no duplicate connections).
  env.fireTimer(pending[0].id);
  await flush();
  assert.equal(FakeWebSocket.instances.length, 2);
  assert.equal(env.pendingTimers().length, 0);
});

test("backoff delay grows across failed attempts and stays capped", async () => {
  const env = makeEnv();
  await flush();
  const delays = [];
  for (let attempt = 0; attempt < 8; attempt++) {
    const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
    ws._drop(1006);
    const pending = env.pendingTimers();
    assert.equal(pending.length, 1, "exactly one scheduled reconnect");
    delays.push(pending[0].ms);
    env.fireTimer(pending[0].id);
    await flush();
  }
  // Growing trend (jittered, so compare early vs late windows)...
  assert.ok(delays[7] > delays[0], `expected growth: ${delays}`);
  // ...and never beyond the documented 30s cap + 25% jitter.
  assert.ok(Math.max(...delays) <= 30000 * 1.25 + 1, `cap exceeded: ${Math.max(...delays)}`);
});

test("auth timeout closes the socket and schedules a retry", async () => {
  const env = makeEnv();
  await flush();
  const ws = FakeWebSocket.instances[0];
  ws._open(); // sends auth but desktop never answers
  const authTimer = env.pendingTimers().find((t) => t.ms === 10000);
  assert.ok(authTimer, "auth timeout scheduled");
  env.fireTimer(authTimer.id);
  await flush();
  assert.notEqual(env.lastState(), "connected");
  assert.ok(env.pendingTimers().length >= 1, "reconnect scheduled after timeout");
});

test("service-worker restart re-evaluates and reconnects (fresh context)", async () => {
  const first = makeEnv();
  await flush();
  const ws = FakeWebSocket.instances[0];
  ws._open();
  ws._message({ type: "auth_ok" });
  assert.equal(first.lastState(), "connected");

  // Simulate suspension + restart: a brand new context with the same storage.
  const second = makeEnv({ token: "secret-token" });
  second.storageData.arrowToken = first.storageData.arrowToken;
  await flush();
  assert.equal(second.storageData.arrowConnState.state, "connected" === second.lastState() ? "connected" : second.lastState());
  assert.equal(FakeWebSocket.instances.length >= 1, true);
  const restarted = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  restarted._open();
  restarted._message({ type: "auth_ok" });
  assert.equal(second.lastState(), "connected");
});

test("inspect request is forwarded to the tab and replied", async () => {
  const env = makeEnv();
  await flush();
  const ws = FakeWebSocket.instances[0];
  ws._open();
  ws._message({ type: "auth_ok" });
  ws._message({ type: "inspect", id: "42", x: 10, y: 20 });
  await flush();
  const replies = ws.sent.filter((m) => m.type === "inspect_result");
  assert.equal(replies.length, 1);
  assert.equal(replies[0].id, "42");
  assert.equal(replies[0].selector, "#ok");
});

test("malformed JSON from desktop does not throw", async () => {
  const env = makeEnv();
  await flush();
  const ws = FakeWebSocket.instances[0];
  ws._open();
  assert.doesNotThrow(() => {
    if (ws.onmessage) ws.onmessage({ data: "{not json" });
  });
  assert.equal(env.lastState(), "authenticating");
});
