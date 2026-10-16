const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../extensions/chatgpt-image/popup.js'), 'utf8');
const html = fs.readFileSync(path.resolve(__dirname, '../extensions/chatgpt-image/popup.html'), 'utf8');
const ids = [
  'notice', 'version-value', 'connection-title', 'connection-detail', 'checked-at', 'identity',
  'pair-form', 'token-row', 'token', 'pair-hint', 'refresh', 'advanced', 'collect', 'disconnect',
  'latest-job', 'last-job', 'last-job-details', 'last-job-diagnostic', 'relink', 'reload',
  'confirm-account', 'pair'
];

function harness(initialStatus, {statusError = null, reloadStatusError = null, tabId = 7,
  manifestVersion = '0.1.14', manifestError = null} = {}) {
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
    runtime: {getManifest() {
      if (manifestError) throw new Error(manifestError);
      return manifestVersion === null ? {} : {version: manifestVersion};
    }, async sendMessage(message) {
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

test('cleared preflight reports an empty tab without claiming an image was generated', async () => {
  const h = harness({configured: true, account: 'second', connection: {state: 'preflight_complete'},
    active: null, lastJob: {state: 'complete', preflight_ready: true, preflight_uploads_cleared: true}});
  await settle();
  assert.match(h.elements['last-job'].textContent, /คืนแท็บว่างแล้ว/);
  assert.match(h.elements['last-job'].textContent, /ไม่ได้เจนภาพ/);
  assert.doesNotMatch(h.elements['last-job'].textContent, /บันทึกแล้ว/);
  assert.equal(h.elements['latest-job'].hidden, false);
});

test('installed extension version remains visible while offline or when status lookup fails', async t => {
  await t.test('offline status shows the manifest version and no invented check time', async () => {
    const h = harness({configured: true, account: 'second', connection: {state: 'offline', checkedAt: 0},
      active: null, lastJob: null});
    await settle();

    assert.equal(h.elements['version-value'].textContent, '0.1.14');
    assert.equal(h.elements['checked-at'].textContent, 'ตรวจล่าสุด: ยังไม่ได้ตรวจ');
  });

  await t.test('initial status error does not hide the manifest version', async () => {
    const h = harness(null, {statusError: 'MCP unavailable'});
    await settle();

    assert.equal(h.elements['version-value'].textContent, '0.1.14');
    assert.equal(h.elements.notice.hidden, false);
  });

  await t.test('unknown or unavailable manifest metadata falls back without throwing', async () => {
    const unknown = harness(null, {statusError: 'MCP unavailable', manifestVersion: null});
    const unavailable = harness(null, {statusError: 'MCP unavailable', manifestError: 'manifest unavailable'});
    await settle();

    assert.equal(unknown.elements['version-value'].textContent, 'ไม่ทราบ');
    assert.equal(unavailable.elements['version-value'].textContent, 'ไม่ทราบ');
  });
});

test('connection status and a failed latest job are shown separately with a useful input hint', async () => {
  const diagnostic = 'Not submitted. Native image file input missing, ambiguous or incompatible; nothing uploaded.';
  const h = harness({configured: true, account: 'second', connection: {state: 'ready', checkedAt: 1792100000000},
    active: null, lastJob: {state: 'failed', error: diagnostic}});
  await settle();

  assert.equal(h.elements['connection-title'].textContent, 'เชื่อมต่อแล้ว');
  assert.equal(h.elements['latest-job'].hidden, false);
  assert.equal(h.elements['last-job'].textContent, 'ยังเลือกช่องแนบภาพไม่ได้');
  assert.equal(h.elements['last-job-details'].hidden, false);
  assert.equal(h.elements['last-job-diagnostic'].textContent, diagnostic);
  assert.match(h.elements['checked-at'].textContent, /^ตรวจล่าสุด: /);
  assert.notEqual(h.elements['checked-at'].textContent, 'ตรวจล่าสุด: ยังไม่ได้ตรวจ');
});

test('reload copy says it reloads installed local files and does not promise a download', () => {
  assert.match(html, /เวอร์ชันที่กำลังรัน/);
  assert.doesNotMatch(html, /id="version" aria-label=/);
  assert.match(html, /โหลดโค้ดในเครื่องใหม่/);
  assert.match(html, /โหลดไฟล์ส่วนขยายที่ติดตั้งในเครื่องใหม่ ไม่ได้ดาวน์โหลดเวอร์ชันใหม่/);
  assert.doesNotMatch(html, /โหลดส่วนขยายรุ่นล่าสุด/);
  assert.match(html, /ตรวจสถานะอีกครั้ง/);
});

test('popup keeps a stable root width and scrolls content without viewport-width feedback', () => {
  assert.match(html, /html\s*\{(?=[^}]*width:\s*380px)(?=[^}]*min-width:\s*380px)[^}]*\}/s);
  assert.match(html, /body\s*\{(?=[^}]*width:\s*100%)(?=[^}]*max-height:\s*600px)(?=[^}]*overflow-y:\s*auto)[^}]*\}/s);
  assert.doesNotMatch(html, /max-width:\s*100vw/);
  assert.match(html, /header\s*\{(?=[^}]*display:\s*flex)(?=[^}]*flex-wrap:\s*wrap)[^}]*\}/s);
  const nowrapSelectors = [...html.matchAll(/([^{}]+)\{([^{}]+)\}/g)]
    .filter(([, , declarations]) => /white-space:\s*nowrap/.test(declarations))
    .flatMap(([, selectors]) => selectors.split(',').map(selector => selector.trim()));
  assert.ok(nowrapSelectors.includes('h1'));
  assert.ok(nowrapSelectors.includes('#identity'));
});

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
    assert.equal(h.elements['connection-title'].textContent, 'กำลังทำงาน');
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

test('preflight completion is labeled as unsent and not as a saved image', async () => {
  const h = harness({configured: true, account: 'second', tabId: 7,
    connection: {state: 'preflight_complete', detail: 'Uploads are ready; nothing was sent.'},
    active: null, lastJob: {job_id: 'job-1', state: 'complete', preflight_ready: true,
      submitted: false, generated: false, cleanup_status: 'not_requested'}});
  await settle();

  assert.equal(h.elements['connection-title'].textContent, 'เชื่อมต่อแล้ว');
  assert.equal(h.elements['connection-detail'].textContent, 'Uploads are ready; nothing was sent.');
  assert.equal(h.elements['last-job'].textContent, 'อัปโหลดพร้อมแล้ว · ยังไม่ส่งและไม่เจนภาพ');
  assert.doesNotMatch(h.elements['last-job'].textContent, /ภาพ.*บันทึก/);
  assert.equal(h.elements.collect.hidden, true);
});

test('cleared failed uploads are not labeled as a generated image', async () => {
  const h = harness({configured: true, account: 'second', tabId: 7,
    connection: {state: 'ready'}, active: null,
    lastJob: {job_id: 'failed-job', state: 'failed', uploads_cleared: true, submitted: false, generated: false}});
  await settle();
  assert.match(h.elements['last-job'].textContent, /นำไฟล์แนบ.*หยุดก่อนส่ง.*ไม่ได้เจนภาพ/);
  assert.doesNotMatch(h.elements['last-job'].textContent, /ภาพ.*บันทึก/);
});
