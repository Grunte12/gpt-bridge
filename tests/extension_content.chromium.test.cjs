// Offline real-DOM regression. Runtime messaging is mocked; no service worker is loaded.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const source = fs.readFileSync(path.join(__dirname, '../extensions/chatgpt-image/content.js'), 'utf8');
const chat = '/c/123e4567-e89b-12d3-a456-426614174000';
const composer = '<form><div id="prompt-textarea" contenteditable="true"><span data-inline-selection-pill data-system-hint-type="picture_v2">Create image</span></div></form>';
const history = '<article data-message-author-role="user"><h4>You said:</h4><div><span data-testid="file-thumbnail">old.png</span></div></article><article data-message-author-role="assistant"><h4>ChatGPT said:</h4><div>Finished</div></article>';
const mockRuntime = () => {
  window.listeners = [];
  window.clicks = 0;
  document.addEventListener('click', () => window.clicks++);
  window.chrome = {runtime: {onMessage: {
    hasListener: fn => window.listeners.includes(fn),
    addListener: fn => window.listeners.push(fn),
  }, sendMessage: async () => ({ok: true})}};
};
test('actual content.js: real Chromium attachment boundaries and receiver reload', async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  try {
    const context = await browser.newContext({serviceWorkers: 'block'});
    let html = '';
    let unexpectedRequests = 0;
    await context.route('**/*', async route => {
      if (route.request().isNavigationRequest()) return route.fulfill({contentType: 'text/html', body: html});
      unexpectedRequests++;
      return route.abort();
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    async function load(body, path = chat) {
      html = '<!doctype html><meta charset="utf-8"><style>#prompt-textarea{min-height:40px}span{display:inline-block}</style>' + body;
      await page.goto('https://chatgpt.com' + path);
      await page.evaluate(mockRuntime);
      await page.addScriptTag({content: source});
    }
    const inspect = () => page.evaluate(() => new Promise(resolve => window.listeners[0]({type: 'image-inspect'}, {}, resolve)));
    await load(history + composer);
    let result = await inspect();
    assert.equal(result.idle, true);
    assert.match(result.error, /Existing conversation preserved/);
    assert.equal(result.upload_dom.attachment_cards, 0);
    await page.addScriptTag({content: source});
    assert.equal(await page.evaluate(() => window.listeners.length), 1, 'duplicate injection remains one receiver');
    await page.evaluate(() => { window.listeners = []; });
    await page.addScriptTag({content: source});
    assert.equal(await page.evaluate(() => window.listeners.length), 1, 'lost runtime listener is reinstalled');
    assert.equal((await inspect()).idle, true);
    await load(history + composer.replace('</form>', '<span data-testid="file-thumbnail">draft.png</span></form>'));
    result = await inspect();
    assert.equal(result.idle, false);
    assert.match(result.error, /Remove existing attachments/);
    await load(history);
    result = await inspect();
    assert.equal(result.idle, true, 'finished chat without composer is idle but never fresh');
    assert.match(result.error, /Existing conversation preserved/);
    await load('<span data-testid="file-thumbnail">unknown.png</span>', '/');
    result = await inspect();
    assert.equal(result.idle, false);
    assert.match(result.error, /composer unavailable/);
    await load(composer, '/');
    result = await inspect();
    assert.equal(result.fresh, true);
    assert.equal(result.idle, true);
    await page.reload();
    await page.evaluate(mockRuntime);
    await page.addScriptTag({content: source});
    assert.equal((await inspect()).fresh, true, 'receiver reinstalls after document reload');
    assert.equal(await page.evaluate(() => window.clicks), 0);
    assert.equal(unexpectedRequests, 0);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({browser: browser.version(), scenarios: 8, liveNetworkRequests: 0, pageErrors: errors.length}));
  } finally { await browser.close(); }
});
