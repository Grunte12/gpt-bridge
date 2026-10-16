const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const contentSource = fs.readFileSync(path.join(root, 'extensions/chatgpt-image/content.js'), 'utf8');
const workerSource = fs.readFileSync(path.join(root, 'extensions/chatgpt-image/worker.js'), 'utf8');

function contentHarness({label = 'Create image', draft = '', busy = false, user = false, challenge = false, challengeAfterSend = false, newUi = false, inflateWhitespace = false, corruptInsertion = false, conversationTurns = null, conversationBodies = [], imageMode = true, loseImageChipOnInsert = false, attachments = false, controls = true, temporaryChat = false, editorAvailable = true, editorDelayQueries = 0, hiddenRetainedEditor = false, imageReady = false, promptLinkBadge = false, waitForHumanDelete = false, confirmationResponse = null, onConfirmation = null, sendDelayQueries = 0, sendDisabledQueries = 0, hiddenFirstSend = false, changeDuringSend = null, changeAfterSendQueries = 1, chatPath = '/c/123e4567-e89b-12d3-a456-426614174000'} = {}) {
  let now = 0;
  let listener;
  let clicks = 0;
  let finalDeleteClicks = 0;
  let menuOpen = false;
  let busyState = busy;
  let challengeState = challenge;
  let controlsState = controls;
  let dialogOpen = false;
  let remainingEditorDelay = editorDelayQueries;
  let sendQueries = 0;
  const location = {origin: 'https://chatgpt.com', href: `https://chatgpt.com${temporaryChat ? '/?temporary-chat=true' : chatPath}`, pathname: chatPath};
  const hasConversation = () => user || (conversationTurns || []).length > 0;
  const sent = [];
  const chip = {innerText: 'Create image', getClientRects: () => [{}]};
  const composerText = () => `${imageMode ? 'Create image' : ''}${draft ? (imageMode ? ' ' : '') + draft : ''}`;
  class Textarea {
    constructor() { this._value = composerText(); this.disabled = false; }
    querySelector(selector) { return imageMode && (promptLinkBadge ? selector.includes('data-prompt-link-href') : selector.includes('data-inline-selection-pill')) ? chip : null; }
    get value() { return this._value; }
    focus() {}
    dispatchEvent() {}
    getClientRects() { return editorAvailable ? [{}] : []; }
    click() { clicks++; }
  }
  Object.defineProperty(Textarea.prototype, 'value', {get() { return this._value; }, set(v) { this._value = v; }});
  class ContentEditable {
    constructor() { this.innerText = composerText(); this.disabled = false; }
    querySelector(selector) { return imageMode && (promptLinkBadge ? selector.includes('data-prompt-link-href') : selector.includes('data-inline-selection-pill')) ? chip : null; }
    get textContent() { return this.innerText; }
    focus() {}
    dispatchEvent() {}
    getClientRects() { return editorAvailable ? [{}] : []; }
  }
  const editor = newUi ? new ContentEditable() : new Textarea();
  const hiddenOldEditor = {value: 'completed conversation content', innerText: 'completed conversation content',
    querySelector() { return null; }, getClientRects: () => []};
  const setEditorText = value => { if (newUi) editor.innerText = value; else editor._value = value; };
  const send = {get disabled() { return sendQueries <= sendDelayQueries + sendDisabledQueries; }, getClientRects: () => [{}], click() { clicks++; }};
  const hiddenSend = {disabled: false, getClientRects: () => []};
  const picker = {textContent: label, getClientRects: () => [{}]};
  const button = (textContent, ariaLabel, isVisible, onClick = () => {}) => ({
    textContent, innerText: textContent, disabled: false, getAttribute(name) { return name === 'aria-label' ? ariaLabel : null; },
    getClientRects: () => isVisible() ? [{}] : [], click() { clicks++; onClick(); }
  });
  const newChatButton = button('New chat', 'New chat', () => controlsState && hasConversation(), () => {
    user = false; conversationTurns = []; conversationBodies = []; imageMode = false; draft = ''; setEditorText(''); menuOpen = false;
  });
  const filesButton = button('Add files and more', 'Add files and more', () => controlsState && !hasConversation() && !busyState && !challengeState && !challengeAfterSend && !attachments, () => { menuOpen = true; });
  const createImageButton = button('Create imageVisualize anything', null, () => controlsState && menuOpen, () => {
    imageMode = true; setEditorText('Create image'); menuOpen = false;
  });
  const moreButton = {...button('More', 'More', () => controlsState), dispatchEvent(event) {
    if (event.type === 'pointerdown' && event.bubbles && event.button === 0 &&
        event.pointerType === 'mouse' && event.isPrimary) {
      clicks++;
      menuOpen = true;
    }
  }};
  const deleteItem = {textContent: 'Delete', getClientRects: () => menuOpen ? [{}] : [], click() { clicks++; dialogOpen = true; menuOpen = false; }};
  const finalDeleteButton = {textContent: 'Delete chat', listeners: new Set(), getClientRects: () => dialogOpen ? [{}] : [],
    addEventListener(type, fn) { if (type === 'click') this.listeners.add(fn); },
    removeEventListener(type, fn) { if (type === 'click') this.listeners.delete(fn); },
    click(event = {isTrusted: false}) { clicks++; finalDeleteClicks++; for (const fn of this.listeners) fn(event); location.pathname = '/'; dialogOpen = false; }};
  const deleteDialog = {getClientRects: () => dialogOpen ? [{}] : [], querySelectorAll(selector) { return selector === 'button' ? [finalDeleteButton] : []; }};
  const displayedImage = {src: 'https://chatgpt.com/generated.png', currentSrc: 'https://chatgpt.com/generated.png',
    complete: true, naturalWidth: 512, naturalHeight: 512, getClientRects: () => [{}]};
  const conversation = {getClientRects: () => [{}], querySelectorAll(selector) {
    if (selector === 'img') return imageReady ? [displayedImage] : [];
    if (selector === 'h4') return (conversationTurns || []).map((textContent, index) => ({
      textContent, nextElementSibling: conversationBodies[index] ? {
        innerText: conversationBodies[index],
        querySelector(selector) { return imageMode && (promptLinkBadge ? selector.includes('data-prompt-link-href') : selector.includes('data-inline-selection-pill')) ? chip : null; }
      } : null,
      getClientRects: () => [{}]
    }));
    return [];
  }};
  const document = {
    querySelector(selector) {
      if ((newUi && selector.includes('[aria-label="Ask ChatGPT"]')) || selector.startsWith('#prompt-textarea')) {
        if (remainingEditorDelay > 0) { remainingEditorDelay--; return null; }
        return editor;
      }
      if (selector === '[data-testid="model-switcher-dropdown-button"]' || selector.includes('[aria-label="Select ChatGPT model"]')) return picker;
      if (selector === '[data-testid="stop-button"]' || selector.includes('button[aria-label="Stop"]')) return busyState ? {getClientRects: () => [{}]} : null;
      if (selector.includes('[aria-label="Conversation"]')) return conversation;
      if (selector === 'button[aria-label="New chat"]') return newChatButton;
      if (selector === 'button[aria-label="Add files and more"]') return filesButton;
      if (selector === 'button[aria-label="More"]') return moreButton;
      if (selector === '[role="dialog"]') return dialogOpen ? deleteDialog : null;
      if (selector.includes('input[type="file"]')) return attachments ? {files: [{}]} : null;
      if (selector.includes('[data-testid="file-upload-progress"]') || selector.includes('[data-testid="attachment-preview"]') || selector.includes('[data-testid="file-thumbnail"]')) return attachments ? {} : null;
      if (selector === '[data-message-author-role="user"]') return user ? {} : null;
      return null;
    },
    querySelectorAll(selector) {
      if (selector.includes('[data-testid="send-button"]') || selector.includes('button[aria-label="Send"]')) {
        sendQueries++;
        if (sendQueries === changeAfterSendQueries) {
          if (changeDuringSend === 'text') setEditorText(`${composerText()} changed`);
          if (changeDuringSend === 'chip') imageMode = false;
          if (changeDuringSend === 'busy') busyState = true;
        }
        if (sendQueries <= sendDelayQueries) return [];
        return hiddenFirstSend ? [hiddenSend, send] : [send];
      }
      if (selector.includes('[role="textbox"]') || selector.includes('textarea#prompt-textarea'))
        return hiddenRetainedEditor ? [hiddenOldEditor, editor] : [editor];
      if (selector === '[role="menuitem"]') return [deleteItem];
      if (selector === '[role="dialog"]') return dialogOpen ? [deleteDialog] : [];
      if (selector.startsWith('button')) return [newChatButton, filesButton, createImageButton, moreButton].filter(item =>
        selector === 'button' || selector.includes(`aria-label="${item.getAttribute('aria-label')}"`));
      if (selector.includes('challenges.cloudflare.com') && (challengeState || (challengeAfterSend && clicks)))
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
    async sendMessage(message) {
      sent.push(message);
      if (message.type === 'image-delete-prompt') return {ok: true};
      if (message.type === 'image-delete-confirmation') {
        onConfirmation?.(message);
        return typeof confirmationResponse === 'function' ? confirmationResponse(message) : (confirmationResponse || {});
      }
      return {};
    }
  }};
  const context = {
    chrome, document, location,
    HTMLTextAreaElement: Textarea, Event: class {}, InputEvent: class {},
    PointerEvent: class { constructor(type, init = {}) { this.type = type; Object.assign(this, init); } }, Date: SimDate,
    setTimeout(fn, ms) {
      if (waitForHumanDelete && ms === 250) { now += ms; setImmediate(fn); }
      else { now += ms; queueMicrotask(fn); }
      return 1;
    }, clearTimeout() {},
    URL, AbortSignal, async fetch() { return {ok: true, async blob() { return {type: 'image/png', size: 32}; }}; },
    FileReader: class { readAsDataURL() { this.result = 'data:image/png;base64,cG5n'; this.onload(); } }
  };
  vm.runInNewContext(contentSource, context, {filename: 'content.js'});
  return {receive: listener, sent, get clicks() { return clicks; }, get finalDeleteClicks() { return finalDeleteClicks; }, editor, location,
    clickMore() { moreButton.click(); }, get deleteMenuOpen() { return menuOpen; },
    setBusy(value) { busyState = value; }, setChallenge(value) { challengeState = value; },
    setControls(value) { controlsState = value; }, setConversationBodies(value) { conversationBodies = value; },
    confirmDelete() { for (const fn of finalDeleteButton.listeners) fn({isTrusted: true}); dialogOpen = false; location.pathname = '/'; },
    trustedClickClosesDialog() { for (const fn of finalDeleteButton.listeners) fn({isTrusted: true}); dialogOpen = false; },
    syntheticDeleteClick() { finalDeleteButton.click({isTrusted: false}); },
    closeDeleteDialog() { dialogOpen = false; },
    setFinalDeleteDisabled(value) { finalDeleteButton.disabled = value; },
    delayedPathChange() { setImmediate(() => { location.pathname = '/'; }); }};
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

async function startPrepare(harness, expectedModel = 'Create image', prompt) {
  let result;
  const job = {expected_model: expectedModel};
  if (prompt !== undefined) job.prompt = prompt;
  harness.receive({type: 'image-prepare', job}, {}, value => { result = value; });
  await new Promise(resolve => setImmediate(resolve));
  return result;
}

async function primeArchiveTarget(overrides = {}) {
  const prompt = 'Create one image. Return a generated image, not just a description.\n\ndraw a cat';
  const h = contentHarness({newUi: true, user: true, conversationTurns: ['You said:', 'ChatGPT said:'],
    conversationBodies: [`Create image ${prompt}`], imageReady: true, promptLinkBadge: true, waitForHumanDelete: true, ...overrides});
  const accepted = await startCollect(h);
  assert.ok(accepted?.accepted);
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-result' && message.imageBase64); i++)
    await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.sent.some(message => message.type === 'image-result' && message.imageBase64), 'saved image receipt must exist before cleanup');
  return h;
}

async function requestDelete(harness, overrides = {}) {
  let result;
  harness.receive({type: 'image-delete', jobId: 'job-collect', chatPath: harness.location.pathname, ...overrides}, {}, value => { result = value; });
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  return result;
}

test('image preparation leaves an already-fresh native image chat unchanged', async () => {
  const h = contentHarness();
  const result = await startPrepare(h);
  assert.deepEqual({...result}, {fresh: true, model: 'Create image'});
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.value, 'Create image');
});

test('inspection selects the visible composer when a hidden retained composer comes first', () => {
  const h = contentHarness({newUi: true, hiddenRetainedEditor: true});
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.deepEqual({...result}, {fresh: true, model: 'Create image'});
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.innerText, 'Create image');
});

test('image preparation turns a completed chat into a fresh native image chat through visible controls', async () => {
  const h = contentHarness({newUi: true, user: true, conversationTurns: ['You said:', 'ChatGPT said:'], imageMode: false, hiddenRetainedEditor: true});
  const result = await startPrepare(h);
  assert.deepEqual({...result}, {fresh: true, model: 'Create image'});
  assert.equal(h.clicks, 3);
  assert.equal(h.editor.innerText, 'Create image');
});

test('image preparation waits for a temporarily unmounted composer and does not submit', async () => {
  const h = contentHarness({editorDelayQueries: 3});
  const result = await startPrepare(h);
  assert.deepEqual({...result}, {fresh: true, model: 'Create image'});
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.value, 'Create image');
  assert.equal(h.sent.length, 0);
});

test('image preparation accepts only a matching unsent image draft', async () => {
  const prompt = 'draw a cat';
  const draft = `Create one image. Return a generated image, not just a description.\n\n${prompt}`;
  const h = contentHarness({draft});
  const result = await startPrepare(h, 'Create image', prompt);
  assert.deepEqual({...result}, {fresh: true, model: 'Create image'});
  assert.equal(h.editor.value, `Create image ${draft}`);
  assert.equal(h.clicks, 0);
});

test('image preparation refuses drafts, running work, challenges, attachments, and wrong expected model', async () => {
  for (const [name, options, expectedModel] of [
    ['draft', {draft: 'keep this'}, 'Create image'],
    ['running work', {busy: true}, 'Create image'],
    ['challenge', {challenge: true}, 'Create image'],
    ['attachments', {attachments: true}, 'Create image'],
    ['temporary chat', {temporaryChat: true}, 'Create image'],
    ['missing composer', {editorAvailable: false}, 'Create image'],
    ['wrong expected model', {}, 'GPT-6 Thinking']
  ]) {
    const h = contentHarness(options);
    const originalText = h.editor.value;
    const result = await startPrepare(h, expectedModel);
    assert.ok(result?.error, `${name} should be refused`);
    assert.equal(h.clicks, 0, `${name} should not activate UI controls`);
    assert.equal(h.editor.value, originalText, `${name} should preserve the editor`);
  }
});

test('image preparation fails closed when visible new-chat or image-mode controls are unavailable', async () => {
  for (const options of [
    {user: true, conversationTurns: ['You said:'], controls: false},
    {controls: false, imageMode: false}
  ]) {
    const h = contentHarness(options);
    const originalText = h.editor.value;
    const result = await startPrepare(h);
    assert.ok(result?.error);
    assert.equal(h.clicks, 0);
    assert.equal(h.editor.value, originalText);
  }
});

test('delete requires a saved image receipt from this worker before it can target a chat', async () => {
  const h = contentHarness({newUi: true, user: true, conversationTurns: ['You said:', 'ChatGPT said:'],
    conversationBodies: ['Create image Create one image. Return a generated image, not just a description. draw a cat']});
  const result = await requestDelete(h);
  assert.match(result.error, /Only this worker's saved image chat can be deleted/);
  assert.equal(h.clicks, 0);
  assert.match(h.location.pathname, /^\/c\//);
});

test('delete opens exact native Delete confirmation after the saved image receipt but never clicks final Delete chat', async () => {
  const h = await primeArchiveTarget();
  const receipt = h.sent.find(message => message.type === 'image-result' && message.imageBase64);
  assert.equal(receipt.chatPath, h.location.pathname);
  assert.equal(receipt.jobId, 'job-collect');
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++)
    await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.sent.some(message => message.type === 'image-delete-prompt' && message.jobId === 'job-collect'));
  assert.equal(h.clicks, 2, 'only More and the menu Delete are clicked; final Delete chat remains human-confirmed');
  assert.match(h.location.pathname, /^\/c\//);
  h.confirmDelete(); // simulate the human's separate final action
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual({...result}, {deleted: true});
  assert.equal(h.clicks, 2, 'the final confirmation button was never clicked by the extension');
  const repeated = await requestDelete(h);
  assert.match(repeated.error, /Only this worker's saved image chat can be deleted/);
  assert.equal(h.clicks, 2);
});

test('More menu opens only from the native primary mouse pointerdown, not click()', () => {
  const h = contentHarness();
  h.clickMore();
  assert.equal(h.deleteMenuOpen, false);
  h.receive({type: 'image-delete'}, {}, () => {});
  assert.equal(h.deleteMenuOpen, false);
});

test('navigation without a trusted final Delete chat click refuses', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++) await new Promise(resolve => setImmediate(resolve));
  h.location.pathname = '/';
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.match(result.error, /without deletion confirmation/);
  assert.equal(h.clicks, 2);
});

test('an untrusted synthetic final Delete chat click does not authorize deletion', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++) await new Promise(resolve => setImmediate(resolve));
  h.syntheticDeleteClick();
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.match(result.error, /without deletion confirmation/);
  assert.equal(h.clicks, 3, 'one synthetic click plus the two automated menu clicks; no trusted action');
});

test('trusted user final click followed by path change passes', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++) await new Promise(resolve => setImmediate(resolve));
  h.confirmDelete();
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual({...result}, {deleted: true});
  assert.equal(h.clicks, 2, 'the final button is confirmed by a trusted user event, never extension-clicked');
});

test('trusted click may close dialog before delayed path change', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++) await new Promise(resolve => setImmediate(resolve));
  h.trustedClickClosesDialog();
  h.delayedPathChange();
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual({...result}, {deleted: true});
  assert.equal(h.clicks, 2);
});

test('one explicit MCP approval clicks final Delete once and completes cleanup', async () => {
  const h = await primeArchiveTarget({confirmationResponse: {confirmed: true}});
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 20 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual({...result}, {deleted: true});
  assert.equal(h.finalDeleteClicks, 1);
  assert.equal(h.clicks, 3, 'two menu activations plus one approved final click');
  assert.equal(h.sent.filter(message => message.type === 'image-delete-confirmation').length, 1,
    'the successful job-scoped approval is consumed once');
});

test('false MCP confirmation never clicks final Delete', async () => {
  const h = await primeArchiveTarget({confirmationResponse: {confirmed: false}, onConfirmation() { h.closeDeleteDialog(); }});
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 20 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.match(result.error, /Deletion was not confirmed/);
  assert.equal(h.finalDeleteClicks, 0);
  assert.equal(h.sent.filter(message => message.type === 'image-delete-confirmation').length, 1);
});

test('MCP approval fails closed if dialog, path, draft, or button state changed', async () => {
  const cases = [
    ['dialog', h => h.closeDeleteDialog()],
    ['path', h => { h.location.pathname = '/'; }],
    ['draft', h => { h.editor.innerText = 'Create image unsent draft'; }],
    ['disabled button', h => h.setFinalDeleteDisabled(true)]
  ];
  for (const [name, mutate] of cases) {
    let harness;
    harness = await primeArchiveTarget({confirmationResponse: {confirmed: true}, onConfirmation: () => mutate(harness)});
    let result;
    harness.receive({type: 'image-delete', jobId: 'job-collect', chatPath: harness.location.pathname}, {}, value => { result = value; });
    for (let i = 0; i < 20 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
    assert.ok(result?.error, `${name} change must fail closed`);
    assert.equal(harness.finalDeleteClicks, 0, `${name} change must not click final Delete`);
    assert.equal(harness.sent.filter(message => message.type === 'image-delete-confirmation').length, 1);
  }
});

test('delete refuses an unknown job or mismatched chat path without opening menus', async () => {
  for (const overrides of [{jobId: 'other-job'}, {chatPath: '/c/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}]) {
    const h = await primeArchiveTarget();
    const result = await requestDelete(h, overrides);
    assert.ok(result?.error);
    assert.equal(h.clicks, 0);
    assert.match(h.location.pathname, /^\/c\//);
  }
});

test('closing the native confirmation without changing chat path fails without a final Delete chat click', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++)
    await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.sent.some(message => message.type === 'image-delete-prompt'));
  h.closeDeleteDialog();
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.match(result.error, /Deletion was not confirmed/);
  assert.equal(h.clicks, 2);
  assert.match(h.location.pathname, /^\/c\//);
});

test('delete refuses changed prompt, draft, running work, challenge, or unavailable controls', async () => {
  const cases = [
    ['changed prompt', h => h.setConversationBodies(['wrong prompt', 'assistant'])],
    ['draft', h => { h.editor.innerText = 'unsent draft'; }],
    ['running work', h => h.setBusy(true)],
    ['challenge', h => h.setChallenge(true)],
    ['missing controls', h => h.setControls(false)]
  ];
  for (const [name, mutate] of cases) {
    const h = await primeArchiveTarget();
    mutate(h);
    const result = await requestDelete(h);
    assert.ok(result?.error, `${name} must fail closed`);
    assert.equal(h.clicks, 0, `${name} must not click More or Archive`);
    assert.match(h.location.pathname, /^\/c\//);
  }
});

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

test('pairing inspection without a job refuses even an otherwise matching image draft', () => {
  const h = contentHarness({draft: 'Create one image. Return a generated image, not just a description.\n\ndraw a cat'});
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.match(result.error, /fresh empty chat/);
  assert.equal(h.clicks, 0);
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

test('matching unsent prompt is reused without duplicate insertion before Send', async () => {
  const prompt = 'draw a cat';
  const draft = 'Create one image. Return a generated image, not just a description.\n\n' + prompt;
  const h = contentHarness({newUi: true, draft});
  await startContent(h, {job_id: 'job-reuse', expected_model: 'Create image', prompt});
  assert.equal(h.clicks, 1);
  assert.equal(h.editor.innerText, `Create image ${draft}`);
  assert.equal(h.sent.length, 1);
});

test('native Send lookup waits for a delayed button mount', async () => {
  const h = contentHarness({sendDelayQueries: 3});
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
});

test('native Send lookup waits until the mounted button is enabled', async () => {
  const h = contentHarness({sendDisabledQueries: 4});
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
});

test('native Send lookup skips a hidden matching button and clicks the visible one', async () => {
  const h = contentHarness({hiddenFirstSend: true});
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
});

test('native Send that never becomes ready is not clicked', async () => {
  const h = contentHarness({sendDisabledQueries: 1000});
  await startContent(h);
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Native send button unavailable/);
});

test('draft, lost image chip, busy state, or changed text while waiting for Send fails closed', async () => {
  for (const [name, changeDuringSend, error] of [
    ['unrelated draft', null, /fresh empty chat/],
    ['lost image chip', 'chip', /Native send button unavailable/],
    ['busy state', 'busy', /fresh empty chat/],
    ['changed text', 'text', /Composer text changed/]
  ]) {
    const options = name === 'unrelated draft' ? {draft: 'keep this'} : {changeDuringSend};
    const h = contentHarness({...options, sendDelayQueries: name === 'unrelated draft' ? 0 : 1});
    await startContent(h);
    assert.equal(h.clicks, 0, `${name} must not click Send`);
    assert.match(h.sent[0].error, error, `${name} must fail closed`);
    assert.match(h.sent[0].error, /Not submitted/);
  }
});

test('losing the native Create image chip during insertion fails closed before Send', async () => {
  const h = contentHarness({newUi: true, loseImageChipOnInsert: true});
  await startContent(h);
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Native send button unavailable/);
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
  assert.match(h.sent[0].error, /Not submitted.*Composer text changed/);
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
