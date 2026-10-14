const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function background() {
  const sockets = [];
  const pendingTokens = [];
  let storageChanged;
  class Socket {
    static CONNECTING = 0;
    static OPEN = 1;
    constructor() { this.readyState = 0; sockets.push(this); }
    send() {}
    close() { this.readyState = 3; }
  }
  const sandbox = {WebSocket: Socket, console, setTimeout: () => 1, clearTimeout() {},
    chrome: {storage: {local: {get: () => new Promise(resolve => pendingTokens.push(resolve))},
      onChanged: {addListener: callback => { storageChanged = callback; }}},
      action: {setBadgeText() {}, setBadgeBackgroundColor() {}}, tabs: {}}};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../browser_extension/background.js'), 'utf8'), sandbox);
  return {sandbox, sockets, pendingTokens, storageChanged: (...args) => storageChanged(...args)};
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test('concurrent connect calls create only one websocket', async () => {
  const state = background();
  vm.runInContext('connect()', state.sandbox);
  state.pendingTokens.forEach(resolve => resolve({bluelyToken: 'token'}));
  await flush();
  assert.equal(state.sockets.length, 1);
});

test('saving a new token invalidates a pending old token read', async () => {
  const state = background();
  state.storageChanged({bluelyToken: {newValue: 'new'}}, 'local');
  state.pendingTokens[0]({bluelyToken: 'old'});
  await flush();
  assert.equal(state.sockets.length, 0);
  state.pendingTokens[1]({bluelyToken: 'new'});
  await flush();
  assert.equal(state.sockets.length, 1);
});

test('selectors escape IDs and classes that contain CSS punctuation', () => {
  const sandbox = {chrome: {runtime: {onMessage: {addListener() {}}}},
    document: {body: {}, documentElement: {}},
    CSS: {escape: s => s.replace(/[.:]/g, '\\$&')}};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../browser_extension/content.js'), 'utf8'), sandbox);
  sandbox.element = {id: 'button:save', tagName: 'BUTTON'};
  assert.equal(vm.runInContext('generateSelector(element)', sandbox), '#button\\:save');
  sandbox.element = {id: '', tagName: 'BUTTON', className: 'hover:bg.red', parentElement: null};
  assert.equal(vm.runInContext('generateSelector(element)', sandbox), 'button.hover\\:bg\\.red');
});

test('React inspection can execute in the page JavaScript world', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../browser_extension/manifest.json'), 'utf8'));
  assert.ok(manifest.permissions.includes('scripting'));
  const state = background();
  const parent = {type: {name: 'App'}, return: null};
  const component = {type: {name: 'Button'}, return: parent,
    _debugSource: {fileName: 'src/Button.tsx', lineNumber: 4, columnNumber: 2}};
  state.sandbox.document = {querySelector: () => ({'__reactFiber$test': {type: 'button', return: component}})};
  const result = vm.runInContext('readReactMetadata("#save")', state.sandbox);
  assert.equal(result.reactComponents, 'App > Button');
  assert.equal(result.reactSource.fileName, 'src/Button.tsx');
  assert.equal(result.reactSource.lineNumber, 4);
});
