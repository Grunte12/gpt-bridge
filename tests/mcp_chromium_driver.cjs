// JSON-lines control for mcp-chromium-readiness.py; never uses an owner profile.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const port = Number(process.argv[2]);
assert.ok(port > 0 && port < 65536 && port !== 18767);
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-mv3-'));
let context;
(async () => {
  const extension = path.join(temp, 'extension');
  fs.cpSync(path.join(root, 'extensions/chatgpt-image'), extension, {recursive:true});
  const workerPath = path.join(extension, 'worker.js');
  const original = fs.readFileSync(workerPath, 'utf8');
  assert.equal(original.split('http://127.0.0.1:18767').length, 2);
  fs.writeFileSync(workerPath, original.replace('http://127.0.0.1:18767', `http://127.0.0.1:${port}`));
  const manifestPath = path.join(extension, 'manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath));
  manifest.permissions = manifest.permissions.filter(value => value !== 'nativeMessaging');
  manifest.host_permissions = manifest.host_permissions.map(value => value.replace(':18767/', `:${port}/`));
  fs.writeFileSync(manifestPath, JSON.stringify(manifest));
  context = await chromium.launchPersistentContext(path.join(temp, 'profile'), {
    headless:true, channel:'chromium',
    ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {}),
    args:[`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
  });
  let blockedNetwork = 0;
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === `http://127.0.0.1:${port}`) return route.continue();
    if (url.origin === 'https://chatgpt.com' && route.request().isNavigationRequest()) {
      return route.fulfill({contentType:'text/html', body:'<!doctype html><form><div id="prompt-textarea" contenteditable="true"><span data-inline-selection-pill data-system-hint-type="picture_v2">Create image</span></div><span data-testid="file-thumbnail">draft.png</span></form><style>#prompt-textarea{min-height:40px}span{display:inline-block}</style>'});
    }
    blockedNetwork++;
    return route.abort();
  });
  const sw = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('https://chatgpt.com/');
  await sw.evaluate(async () => {
    await chrome.alarms.clearAll();
    globalThis.deliveries = [];
    const nativeSend = chrome.tabs.sendMessage.bind(chrome.tabs);
    // Synthetic generation only: all readiness/identity messages remain native.
    chrome.tabs.sendMessage = async (id, message, ...rest) => {
      if (message.type === 'image-job') {
        globalThis.deliveries.push(message.job.job_id);
        return {accepted:true};
      }
      return nativeSend(id, message, ...rest);
    };
  });
  const [tab] = await sw.evaluate(() => chrome.tabs.query({url:'https://chatgpt.com/*'}));
  // Wait for the manifest's actual isolated-world content script, no injection.
  let inspected;
  for (let attempt=0; attempt<50; attempt++) {
    try {inspected = await sw.evaluate(id => chrome.tabs.sendMessage(id, {type:'image-inspect'}), tab.id); break;}
    catch (_) {await new Promise(resolve => setTimeout(resolve, 50));}
  }
  assert.ok(inspected, 'manifest content script responds through native tabs messaging');
  const send = value => process.stdout.write(JSON.stringify(value)+'\n');
  const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
  send({ready:true, browser:context.browser()?.version(), serviceWorker:sw.url(), tabId:tab.id,
    contentSha256:sha256(fs.readFileSync(path.join(extension, 'content.js'))),
    originalWorkerSha256:sha256(original), inspected});
  for await (const line of readline.createInterface({input:process.stdin})) {
    const command = JSON.parse(line);
    try {
      let result;
      if (command.op === 'configure') {
        result = await sw.evaluate(async ({id, token, clientId}) => {
          await chrome.storage.local.set({config:{tabId:id, token, clientId}});
          await chrome.tabs.sendMessage(id, {type:'image-bind', clientId});
          await poll();
          return chrome.storage.local.get(['connection']);
        }, {id:tab.id, token:command.token, clientId:command.clientId});
      } else if (command.op === 'dom') {
        await page.evaluate(mode => {
          document.querySelector('[data-testid="file-thumbnail"]')?.remove();
          const composer = document.querySelector('#prompt-textarea');
          if (mode === 'missing') composer?.remove();
          if (mode === 'clean' && !composer) {
            document.querySelector('form').innerHTML = '<div id="prompt-textarea" contenteditable="true"><span data-inline-selection-pill data-system-hint-type="picture_v2">Create image</span></div>';
          }
        }, command.mode);
        result = await sw.evaluate(async id => {
          const inspected = await chrome.tabs.sendMessage(id, {type:'image-inspect'});
          await poll();
          return {inspected, deliveries:globalThis.deliveries};
        }, tab.id);
      } else if (command.op === 'poll') {
        result = await sw.evaluate(async () => {await poll(); return {deliveries:globalThis.deliveries};});
      } else if (command.op === 'close') {
        send({ok:true, blockedNetwork, pageErrors:errors}); break;
      } else throw new Error('Unknown command');
      send(result);
    } catch (error) {send({driver_error:error.stack});}
  }
})().catch(error => {console.error(error);process.exitCode=1;}).finally(async () => {
  try { if (context) await context.close(); }
  finally { fs.rmSync(temp, {recursive:true, force:true}); }
});
