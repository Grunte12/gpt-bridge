const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const contentSource = fs.readFileSync(path.join(root, 'extensions/chatgpt-image/content.js'), 'utf8');
const workerSource = fs.readFileSync(path.join(root, 'extensions/chatgpt-image/worker.js'), 'utf8');

function contentHarness({label = 'Create image', draft = '', busy = false, user = false, challenge = false, challengeAfterSend = false, newUi = false, inflateWhitespace = false, corruptInsertion = false, conversationTurns = null, conversationBodies = [], imageMode = true, loseImageChipOnInsert = false} = {}) {
  let now = 0;
  let listener;
  let clicks = 0;
  const sent = [];
  const chip = {innerText: 'Create image', getClientRects: () => [{}]};
  const composerText = () => `${imageMode ? 'Create image' : ''}${draft ? (imageMode ? ' ' : '') + draft : ''}`;
  class Textarea {
    constructor() { this._value = composerText(); this.disabled = false; }
    querySelector(selector) { return imageMode && selector.includes('data-inline-selection-pill') ? chip : null; }
    get value() { return this._value; }
    focus() {}
    dispatchEvent() {}
    getClientRects() { return [{}]; }
    click() { clicks++; }
  }
  Object.defineProperty(Textarea.prototype, 'value', {get() { return this._value; }, set(v) { this._value = v; }});
  class ContentEditable {
    constructor() { this.innerText = composerText(); this.disabled = false; }
    querySelector(selector) { return imageMode && selector.includes('data-inline-selection-pill') ? chip : null; }
    get textContent() { return this.innerText; }
    focus() {}
    dispatchEvent() {}
    getClientRects() { return [{}]; }
  }
  const editor = newUi ? new ContentEditable() : new Textarea();
  const send = {disabled: false, getClientRects: () => [{}], click() { clicks++; }};
  const picker = {textContent: label, getClientRects: () => [{}]};
  const conversation = {getClientRects: () => [{}], querySelectorAll(selector) {
    if (selector === 'h4') return (conversationTurns || []).map((textContent, index) => ({
      textContent, nextElementSibling: conversationBodies[index] ? {
        innerText: conversationBodies[index],
        querySelector(selector) { return imageMode && selector.includes('data-inline-selection-pill') ? chip : null; }
      } : null,
      getClientRects: () => [{}]
    }));
    return [];
  }};
  const document = {
    querySelector(selector) {
      if (newUi && selector.includes('[aria-label="Ask ChatGPT"]')) return editor;
      if (selector.startsWith('#prompt-textarea')) return editor;
      if (selector === '[data-testid="model-switcher-dropdown-button"]' || selector.includes('[aria-label="Select ChatGPT model"]')) return picker;
      if (selector === '[data-testid="stop-button"]' || selector.includes('button[aria-label="Stop"]')) return busy ? {getClientRects: () => [{}]} : null;
      if (selector.includes('[aria-label="Conversation"]')) return conversation;
      if (selector === '[data-testid="send-button"]' || selector.includes('[aria-label="Send"]')) return send;
      if (selector === '[data-message-author-role="user"]') return user ? {} : null;
      return null;
    },
    querySelectorAll(selector) {
      if (selector.includes('challenges.cloudflare.com') && (challenge || (challengeAfterSend && clicks)))
        return [{getClientRects: () => [{}]}];
      if (selector.includes('h4') && !selector.startsWith('region'))
        return (conversationTurns || []).map(textContent => ({textContent, getClientRects: () => [{}]}));
      return [];
    },
    execCommand(_cmd, _ui, value) {
      let inserted = corruptInsertion ? value.replace('Create one image', 'Create one cat') : value;
      if (inflateWhitespace) inserted = inserted.replace(/\n\n/g, '\n\n\n\n\n');
      if (newUi) editor.innerText += inserted;
      else editor._value += inserted;
      if (loseImageChipOnInsert) imageMode = false;
      return true;
    }
  };
  const NativeDate = Date;
  class SimDate extends NativeDate { static now() { return now; } }
  const chrome = {runtime: {
    onMessage: {addListener(fn) { listener = fn; }},
    async sendMessage(message) { sent.push(message); return {}; }
  }};
  const context = {
    chrome, document, location: {origin: 'https://chatgpt.com', href: 'https://chatgpt.com/'},
    HTMLTextAreaElement: Textarea, Event: class {}, InputEvent: class {}, Date: SimDate,
    setTimeout(fn, ms) { now += ms; queueMicrotask(fn); return 1; }, clearTimeout() {},
    URL, AbortSignal, fetch() { throw new Error('fetch should not be reached in guard tests'); },
    FileReader: class {}
  };
  vm.runInNewContext(contentSource, context, {filename: 'content.js'});
  return {receive: listener, sent, get clicks() { return clicks; }, editor};
}

async function startContent(harness, job = {job_id: 'job-1', expected_model: 'Create image', prompt: 'draw a cat'}) {
  let accepted;
  harness.receive({type: 'image-job', job}, {}, value => { accepted = value; });
  await new Promise(resolve => setImmediate(resolve));
  return accepted;
}

async function startCollect(harness, expectedModel = 'Create image', prompt = 'draw a cat') {
  let accepted;
  harness.receive({type: 'image-collect', job: {job_id: 'job-collect', expected_model: expectedModel, prompt}}, {}, value => { accepted = value; });
  await new Promise(resolve => setImmediate(resolve));
  return accepted;
}

test('pairing inspection reports native Create image mode without touching the composer', () => {
  const h = contentHarness();
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.equal(result.fresh, true);
  assert.equal(result.model, 'Create image');
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.value, 'Create image');
});

test('pairing inspection rejects a draft or blank model without submitting', () => {
  for (const options of [{draft: 'preserve this draft'}, {imageMode: false}]) {
    const h = contentHarness(options);
    let result;
    h.receive({type: 'image-inspect'}, {}, value => { result = value; });
    assert.match(result.error, /fresh empty chat|model label is empty|Select native Create image/);
    assert.equal(h.clicks, 0);
  }
});

test('content refuses an incompatible route before touching the composer', async () => {
  const h = contentHarness();
  assert.equal((await startContent(h, {job_id: 'job-route', expected_model: 'GPT-6 Thinking', prompt: 'draw'})).accepted, true);
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Native image mode is Create image/);
  assert.match(h.sent[0].error, /Not submitted/);
});

test('plain chat without the native Create image chip refuses before insertion or Send', async () => {
  const h = contentHarness({newUi: true, imageMode: false});
  await startContent(h);
  assert.equal(h.editor.innerText, '');
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Select native Create image/);
});

for (const [name, options] of [
  ['existing draft', {draft: 'keep this'}],
  ['running generation', {busy: true}],
  ['non-empty conversation', {user: true}]
]) {
  test(`content refuses ${name} without clicking send`, async () => {
    const h = contentHarness(options);
    await startContent(h);
    assert.equal(h.clicks, 0);
    assert.match(h.sent[0].error, /fresh empty chat/);
    assert.match(h.sent[0].error, /Not submitted/);
  });
}

test('matching fresh composer inserts once and clicks only native send once', async () => {
  const h = contentHarness();
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.match(h.editor.value, /^Create one image\. Return a generated image, not just a description\./);
  assert.equal(h.sent.length, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
  assert.match(h.sent[0].error, /Timed out/);
});

test('current ChatGPT contenteditable UI inserts exact prompt and clicks native send once', async () => {
  const expectedModel = 'Create image';
  const h = contentHarness({newUi: true});
  assert.equal((await startContent(h, {job_id: 'job-2', expected_model: expectedModel, prompt: 'draw a cat'})).accepted, true);
  assert.equal(h.clicks, 1);
  assert.match(h.editor.innerText, /^Create imageCreate one image\. Return a generated image, not just a description\./);
  assert.equal(h.sent.length, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
  assert.match(h.sent[0].error, /Timed out/);
});

test('losing the native Create image chip during insertion fails closed before Send', async () => {
  const h = contentHarness({newUi: true, loseImageChipOnInsert: true});
  await startContent(h);
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Create image selection did not match/);
});

test('contenteditable paragraph newline inflation does not reject the correct prompt', async () => {
  const expectedModel = 'Create image';
  const h = contentHarness({newUi: true, inflateWhitespace: true});
  await startContent(h, {job_id: 'job-3', expected_model: expectedModel, prompt: 'draw a cat'});
  assert.match(h.editor.innerText, /Create one image\. Return a generated image.*\n{5}draw a cat/);
  assert.equal(h.clicks, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
});

test('whitespace normalization does not accept changed prompt words', async () => {
  const expectedModel = 'Create image';
  const h = contentHarness({newUi: true, inflateWhitespace: true, corruptInsertion: true});
  await startContent(h, {job_id: 'job-4', expected_model: expectedModel, prompt: 'draw a cat'});
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Create image selection did not match/);
});

test('collection-only accepts one existing conversation and never inserts or clicks Send', async () => {
  const originalPrompt = 'Create image Create one image. Return a generated image, not just a description.\n\ndraw a cat';
  const h = contentHarness({newUi: true,
    conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: [originalPrompt]});
  const accepted = await startCollect(h);
  assert.ok(accepted?.accepted);
  assert.equal(h.editor.innerText, 'Create image');
  assert.equal(h.clicks, 0);
});

test('collection-only refuses an existing user turn whose original prompt differs', async () => {
  const h = contentHarness({newUi: true,
    conversationTurns: ['You said:', 'ChatGPT said:'],
    conversationBodies: ['Create image Create one image. Return a generated image, not just a description.\n\ndraw something else']});
  await startCollect(h);
  assert.equal(h.editor.innerText, 'Create image');
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Existing conversation does not match this job's prompt/);
});

test('collection-only rejects a model mismatch and multiple existing turns without Send', async () => {
  for (const [options, expectedModel] of [
    [{conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: ['Create image Create one image. Return a generated image, not just a description.\n\ndraw a cat']}, 'GPT-6 Thinking'],
    [{conversationTurns: ['You said:', 'ChatGPT said:', 'You said:', 'ChatGPT said:']}, 'Create image']
  ]) {
    const h = contentHarness({...options, newUi: true});
    const accepted = await startCollect(h, expectedModel);
    assert.ok(accepted?.accepted);
    assert.equal(h.editor.innerText, 'Create image');
    assert.equal(h.clicks, 0);
    assert.match(h.sent[0].error, /Wrong site or model|Inspect the completed single-turn/);
  }
});

test('collection-only refuses while Stop is visible', async () => {
  const h = contentHarness({newUi: true, busy: true,
    conversationTurns: ['You said:', 'ChatGPT said:']});
  await startCollect(h);
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.innerText, 'Create image');
  assert.match(h.sent[0].error, /Inspect the completed single-turn/);
});

test('visible verification before sending stops without editing or submitting', async () => {
  const h = contentHarness({challenge: true});
  await startContent(h);
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.value, 'Create image');
  assert.match(h.sent[0].error, /Not submitted.*Owner action required/);
});

test('verification after sending stops for owner inspection without retry', async () => {
  const h = contentHarness({challengeAfterSend: true});
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.equal(h.sent.length, 1);
  assert.match(h.sent[0].error, /Submission attempted.*Owner action required/);
});

function workerHarness({config = {token: 'x'.repeat(40), tabId: 7, clientId: 'client'}, active = {jobId: 'job-1', tabId: 7}} = {}) {
  let listener;
  const calls = [];
  const storage = {config, active};
  const chrome = {
    storage: {local: {
      async get(keys) { const out = {}; for (const key of (Array.isArray(keys) ? keys : [keys])) out[key] = storage[key]; return out; },
      async remove(key) { delete storage[key]; }, async set(value) { Object.assign(storage, value); }
    }},
    runtime: {onMessage: {addListener(fn) { listener = fn; }}},
    alarms: {onAlarm: {addListener() {}}, async clear() {}, async create() {}},
    tabs: {async sendMessage() {}}
  };
  const context = {chrome, URL, crypto: {randomUUID: () => 'id'}, AbortSignal,
    async fetch(url, options) { calls.push({url, body: JSON.parse(options.body)}); return {ok: true, json: async () => ({})}; }};
  vm.runInNewContext(workerSource, context, {filename: 'worker.js'});
  return {receive: listener, calls, storage};
}

test('worker rejects unknown or unpaired content results and preserves the active job', async t => {
  const cases = [
    ['unpaired sender', {id: 8, url: 'https://chatgpt.com/'} , 'job-1'],
    ['wrong job', {id: 7, url: 'https://chatgpt.com/'} , 'other-job'],
    ['wrong origin', {id: 7, url: 'https://example.com/'} , 'job-1']
  ];
  for (const [name, sender, jobId] of cases) await t.test(name, async () => {
    const h = workerHarness();
    let response;
    h.receive({type: 'image-result', jobId, imageBase64: 'not-a-real-image'}, sender, value => { response = value; });
    await new Promise(resolve => setImmediate(resolve));
    assert.match(response.error, /not from the paired job\/tab/);
    assert.equal(h.calls.length, 0);
    assert.equal(h.storage.active.jobId, 'job-1');
  });
});
