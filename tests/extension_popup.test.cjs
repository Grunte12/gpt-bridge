const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../extensions/chatgpt-image/popup.js'), 'utf8');
const ids = [
  'notice', 'connection-title', 'connection-detail', 'identity', 'pair-form', 'token-row', 'token',
  'pair-hint', 'refresh', 'advanced', 'collect', 'disconnect', 'last-job', 'relink', 'reload',
  'confirm-account', 'pair'
];

function harness(initialStatus, {statusError = null, reloadStatusError = null, tabId = 7} = {}) {
  const elements = Object.fromEntries(ids.map(id => [id, {
    id, textContent: '', hidden: true, disabled: false, required: false, value: '', checked: false,
    focus() {}
  }]));
  elements['confirm-account'].required = true;
  const body = {dataset: {state: 'checking'}};
  const messages = [];
  let reloads = 0;
  let changedListener;
  const buttons = ['pair', 'refresh', 'relink', 'collect', 'disconnect', 'reload'].map(id => elements[id]);
  const document = {
    body,
    querySelector(selector) { return elements[selector.slice(1)]; },
    querySelectorAll(selector) { return selector === 'button' ? buttons : []; }
  };
  const chrome = {
    runtime: {async sendMessage(message) {
      messages.push(message);
      if (message.type === 'get-status') {
        const error = message.refresh === false ? reloadStatusError : statusError;
        return error ? {error} : initialStatus;
      }
      return {ok: true};
    }, reload() { reloads++; }},
    tabs: {async query() { return [{id: tabId}]; }},
    storage: {onChanged: {addListener(fn) { changedListener = fn; }}}
  };
  vm.runInNewContext(source, {document, chrome}, {filename: 'popup.js'});
  return {elements, body, messages, changedListener, get reloads() { return reloads; }};
}

async function settle() {
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
}

test('connected, offline, and busy states never expose saved key entry', async t => {
  const connected = harness({configured: true, account: 'second', tabId: 7,
    connection: {state: 'ready'}, active: null, lastJob: null});
  await settle();
  assert.equal(connected.elements['pair-form'].hidden, true);
  assert.equal(connected.elements['token-row'].hidden, true);
  assert.equal(connected.elements.token.required, false);
  assert.equal(connected.elements.identity.hidden, false);

  await t.test('offline config keeps token field hidden', async () => {
    const h = harness({configured: true, account: 'second', tabId: 7,
      connection: {state: 'offline'}, active: null, lastJob: null});
    await settle();
    assert.equal(h.elements['pair-form'].hidden, true);
    assert.equal(h.elements['token-row'].hidden, true);
  });

  await t.test('busy config keeps token hidden and prevents forgetting active work', async () => {
    const h = harness({configured: true, account: 'second', tabId: 7,
      connection: {state: 'busy'}, active: {jobId: 'job-1'}, lastJob: null});
    await settle();
    assert.equal(h.elements['pair-form'].hidden, true);
    assert.equal(h.elements['token-row'].hidden, true);
    assert.equal(h.elements.collect.hidden, false);
    assert.equal(h.elements.disconnect.disabled, true);
  });
});

test('first-time setup and rotated-key state show a required token only when needed', async t => {
  const first = harness({configured: false, connection: {state: 'unpaired'}, active: null, lastJob: null});
  await settle();
  assert.equal(first.elements['pair-form'].hidden, false);
  assert.equal(first.elements['token-row'].hidden, false);
  assert.equal(first.elements.token.required, true);
  assert.equal(first.elements['confirm-account'].required, true);

  const rotated = harness({configured: true, account: 'second', tabId: 7,
    connection: {state: 'needs_pairing'}, active: null, lastJob: null});
  await settle();
  assert.equal(rotated.elements['pair-form'].hidden, false);
  assert.equal(rotated.elements['token-row'].hidden, false);
  assert.equal(rotated.elements.token.required, true);
});

test('storage changes request cached get-status without starting a refresh poll', async () => {
  const h = harness({configured: true, account: 'second', tabId: 7,
    connection: {state: 'offline'}, active: null, lastJob: null});
  await settle();

  h.changedListener({connection: {newValue: {state: 'ready'}}}, 'local');
  await settle();

  const last = h.messages.at(-1);
  assert.equal(last.type, 'get-status');
  assert.equal(last.refresh, false);
});

test('relink reveals confirmation but reuses stored key without showing the token field', async () => {
  const h = harness({configured: true, account: 'second', tabId: 7,
    connection: {state: 'ready'}, active: null, lastJob: null});
  await settle();

  h.elements.relink.onclick();
  assert.equal(h.elements['pair-form'].hidden, false);
  assert.equal(h.elements['token-row'].hidden, true);
  assert.equal(h.elements.token.required, false);
  assert.equal(h.elements['confirm-account'].required, true);
  assert.match(h.elements['pair-hint'].textContent, /จำไว้แล้ว/);

  h.elements['confirm-account'].checked = true;
  h.elements['pair-form'].onsubmit({preventDefault() {}});
  await settle();

  const pairMessage = h.messages.find(message => message.type === 'pair');
  assert.equal(pairMessage.tabId, 7);
  assert.equal(pairMessage.account, 'second');
  assert.equal(pairMessage.confirmedAccount, true);
  assert.equal(pairMessage.token, '');
});

test('popup initialization error never displays a ready state', async () => {
  const h = harness(null, {statusError: 'worker unavailable'});
  await settle();
  assert.equal(h.body.dataset.state, 'checking');
  assert.notEqual(h.elements['connection-title'].textContent, 'พร้อมรับงาน');
  assert.equal(h.elements.notice.hidden, false);
  assert.notEqual(h.elements.notice.textContent, '');
});

test('reload requires cached idle status and reloads the extension once', async t => {
  await t.test('idle status reloads once without a fresh poll', async () => {
    const h = harness({configured: true, account: 'second', tabId: 7,
      connection: {state: 'ready'}, active: null, lastJob: null});
    await settle();

    assert.equal(h.elements.reload.disabled, false);
    h.elements.reload.onclick();
    await settle();

    assert.equal(h.reloads, 1);
    assert.ok(h.messages.some(message => message.type === 'get-status' && message.refresh === false));
  });

  await t.test('active job disables reload and cached status refuses it', async () => {
    const h = harness({configured: true, account: 'second', tabId: 7,
      connection: {state: 'busy'}, active: {jobId: 'job-1'}, lastJob: null});
    await settle();

    assert.equal(h.elements.reload.disabled, true);
    h.elements.reload.onclick();
    await settle();

    assert.equal(h.reloads, 0);
    assert.ok(h.messages.some(message => message.type === 'get-status' && message.refresh === false));
  });

  await t.test('status error refuses reload', async () => {
    const h = harness({configured: true, account: 'second', tabId: 7,
      connection: {state: 'ready'}, active: null, lastJob: null}, {reloadStatusError: 'worker unavailable'});
    await settle();
    h.elements.reload.onclick();
    await settle();

    assert.equal(h.reloads, 0);
    assert.equal(h.elements.notice.hidden, false);
  });
});

test('saved image awaiting owner Delete confirmation keeps destructive controls locked', async () => {
  const h = harness({configured: true, account: 'second', tabId: 7,
    connection: {state: 'confirmation_required', detail: 'Confirm Delete chat in ChatGPT'},
    active: {jobId: 'job-1'}, lastJob: {job_id: 'job-1', state: 'complete'}});
  await settle();

  assert.equal(h.elements['connection-title'].textContent, 'บันทึกภาพแล้ว รอยืนยันลบแชท');
  assert.equal(h.elements['connection-detail'].textContent, 'Confirm Delete chat in ChatGPT');
  assert.equal(h.elements['pair-form'].hidden, true);
  assert.equal(h.elements.reload.disabled, true);
  assert.equal(h.elements.disconnect.disabled, true);
  assert.equal(h.elements.collect.hidden, true);
});
