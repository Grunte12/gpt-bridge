const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {createHash} = require('node:crypto');

const source = fs.readFileSync(path.resolve(__dirname, '../extensions/chatgpt-image/worker.js'), 'utf8');
const manifest = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../extensions/chatgpt-image/manifest.json'), 'utf8'));

test('0.1.24 manifest grants only the host access needed for local bridge and ChatGPT reinjection', () => {
  assert.equal(manifest.version, '0.1.24');
  assert.ok(manifest.permissions.includes('scripting'));
  assert.deepEqual(manifest.host_permissions, ['http://127.0.0.1:18767/*', 'https://chatgpt.com/*']);
  for (const permission of ['tabs', 'cookies', 'webRequest', 'debugger'])
    assert.equal(manifest.permissions.includes(permission), false);
});

function harness({tabUrl = 'https://chatgpt.com/', tabUrlRedacted = false, tabExists = true, active = null, state = {state: 'claimed', expected_model: 'Create image'}, next = {}, inspection = {fresh: true, model: 'Create image', input_protocol: 2, idle: true}, preparation = {fresh: true, model: 'Create image', input_protocol: 2, idle: true}, inspectError = '', prepareError = '', deleteResponse = {deleted: true}, deleteError = '', holdDeleteConfirmation = false, autoDeleteConfirmation = false, responses = {}, failPaths = [], storage: sharedStorage = null, failures = 0, httpError = 0, holdPath = '', holdTabLookup = false, scriptingAvailable = false, scriptingError = '', inspectionAfterInjection = null, inspectErrorAfterInjection = '', candidateTabs = [], identities = {}, queryError = ''} = {}) {
  let listener;
  let alarmListener;
  const storage = sharedStorage || {};
  if (active) storage.active = active;
  const requests = [];
  const alarms = [];
  const tabLookups = [];
  const tabMessages = [];
  const scriptInjections = [];
  let releaseNetwork;
  const networkGate = new Promise(resolve => { releaseNetwork = resolve; });
  let releaseTabLookup;
  const tabGate = new Promise(resolve => { releaseTabLookup = resolve; });
  let releaseDeleteConfirmation;
  const deleteGate = new Promise(resolve => { releaseDeleteConfirmation = resolve; });
  let activeInspection = inspection;
  let activeInspectError = inspectError;
  let reloadCalls = 0;
  let replacedListener;
  const scripting = scriptingAvailable ? {async executeScript(details) {
    scriptInjections.push(details);
    if (scriptingError) throw new Error(scriptingError);
    activeInspection = inspectionAfterInjection || activeInspection;
    activeInspectError = inspectErrorAfterInjection;
  }} : undefined;
  const chrome = {
    storage: {local: {
      async get(keys) { const out = {}; for (const key of Array.isArray(keys) ? keys : [keys]) out[key] = storage[key]; return out; },
      async set(values) { Object.assign(storage, values); },
      async remove(keys) { for (const key of Array.isArray(keys) ? keys : [keys]) delete storage[key]; }
    }},
    runtime: {onMessage: {addListener(fn) { listener = fn; }}, getManifest() { return {version: manifest.version}; }, reload() { reloadCalls++; }},
    alarms: {onAlarm: {addListener(fn) { alarmListener = fn; }}, async create(...args) { alarms.push(args); }, async clear(...args) { alarms.push(['clear', ...args]); }},
    tabs: {
      onReplaced: {addListener(fn) { replacedListener = fn; }},
      async query() { if (queryError) throw new Error(queryError); return candidateTabs; },
      async get(id) {
        tabLookups.push(id);
        if (holdTabLookup) await tabGate;
        const candidate = candidateTabs.find(tab => tab.id === id);
        if (candidate) return {...candidate};
        if (!tabExists) return null;
        return {id, ...(tabUrlRedacted ? {} : {url: tabUrl})};
      },
      async sendMessage(id, message) {
        tabMessages.push({id, message});
        if (message.type === 'image-identity') return {client_id: identities[id] || ''};
        if (message.type === 'image-bind') return {ok: true};
        if (message.type === 'image-inspect') {
          if (activeInspectError) throw new Error(activeInspectError);
          return activeInspection;
        }
        if (message.type === 'image-prepare') {
          if (prepareError) throw new Error(prepareError);
          return preparation;
        }
        if (message.type === 'image-delete') {
          if (deleteError) throw new Error(deleteError);
          const reply = await new Promise(resolve => listener({type: 'image-delete-prompt', jobId: message.jobId},
            {tab: {id}, url: `https://chatgpt.com${message.chatPath}`}, resolve));
          if (!reply?.ok) throw new Error(reply?.error || 'Deletion confirmation was not recorded');
          if (autoDeleteConfirmation) {
            const approval = await new Promise(resolve => listener({type: 'image-delete-confirmation', jobId: message.jobId},
              {tab: {id}, url: `https://chatgpt.com${message.chatPath}`}, resolve));
            if (approval?.confirmed !== true) throw new Error('Automatic deletion approval was not confirmed');
          }
          if (holdDeleteConfirmation) await deleteGate;
          return deleteResponse;
        }
        return {accepted: true};
      }
    },
    ...(scripting ? {scripting} : {})
  };
  const context = {chrome, URL, crypto: {randomUUID: () => 'client-id'}, AbortSignal,
    async fetch(url, options) {
      const body = JSON.parse(options.body);
      requests.push({url, body, authorization: options.headers.Authorization});
      if (holdPath && url.endsWith(holdPath)) await networkGate;
      if (failPaths.some(path => url.endsWith(path))) throw new Error('offline');
      if (failures > 0) { failures--; throw new Error('offline'); }
      if (httpError) return {ok: false, status: httpError, json: async () => ({})};
      const route = url.split('/').at(-1);
      const configuredResponse = responses[route];
      const response = route === 'state' ? state : route === 'next' ? next
        : Array.isArray(configuredResponse) ? configuredResponse.shift()
          : configuredResponse || (route === 'cleanup' ? {state: 'complete', cleanup_status: body.cleanup_status} : {});
      return {ok: true, json: async () => response};
    }};
  vm.runInNewContext(source, context, {filename: 'worker.js'});
  return {storage, requests, alarms, tabLookups, tabMessages, scriptInjections, receive: listener,
    get reloadCalls() { return reloadCalls; },
    fireAlarm() { alarmListener({name: 'poll'}); },
    releaseNetwork() { releaseNetwork(); },
    releaseTabLookup() { releaseTabLookup(); },
    releaseDeleteConfirmation() { releaseDeleteConfirmation(); },
    replaceTab(added, removed) { return replacedListener(added, removed); }};
}

const pairedImageResult = (overrides = {}) => ({
  message: {type: 'image-result', jobId: 'job-1', imageBase64: 'cG5n', chatPath: '/c/123e4567-e89b-12d3-a456-426614174000', ...overrides},
  sender: {tab: {id: 7}, url: 'https://chatgpt.com/c/123e4567-e89b-12d3-a456-426614174000'}
});

function referenceImage(order, role, bytes = Buffer.from(`image-${order}`)) {
  return {order, role, description: `Image ${order}`, name: `input-${String(order).padStart(3, '0')}.png`, mime: 'image/png',
    bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'),
    dimensions: {width: 2, height: 2}, data_base64: bytes.toString('base64'), path: `/private/image-${order}.png`};
}

const uploadDom = () => ({editor_form: true, file_inputs: 3, form_file_inputs: 2, image_inputs: 2,
  form_image_inputs: 1, multiple_image_inputs: 1, unrestricted_inputs: 0, attachment_cards: 1});

const resultDom = (overrides = {}) => ({assistant_role_nodes: 2, user_headings: 1, assistant_headings: 1,
  assistant_images: 2, conversation_images: 2, assistant_body_found: true, busy: false,
  chat_path: '/c/123e4567-e89b-12d3-a456-426614174000', ...overrides});

const promptDom = (overrides = {}) => ({body_chars: 2712, stripped_chars: 2700, matched_chip_chars: 12,
  label_count: 1, starts_with_label: true, ends_with_label: false,
  labels: [{tag: 'SPAN', parent_tag: 'DIV', inline_pill: true, system_hint: true,
    prompt_link: false, in_button: false, matched_chip: true}], ...overrides});

const imageJob = images => ({job_id: 'job-1', mode: 'edit', prompt: 'Use the supplied sources',
  expected_model: 'Create image', images});

const cleanupOnlyPreflight = images => ({...imageJob(images), preflight_only: true,
  clear_preflight_uploads: true, preflight_cleanup_only: true});

function metadataOnly(job) {
  return {...job, images: job.images.map(({data_base64, path: localPath, ...image}) => image)};
}

async function send(h, message, sender = {}) {
  let response;
  h.receive(message, sender, value => { response = value; });
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
  return response;
}

const pairing = overrides => ({type: 'pair', tabId: 7, url: 'https://chatgpt.com/',
  token: 'x'.repeat(40), account: 'second', confirmedAccount: true, ...overrides});

for (const [name, overrides, tabUrl] of [
  ['main account', {account: 'main'}, 'https://chatgpt.com/'],
  ['unchecked owner confirmation', {confirmedAccount: false}, 'https://chatgpt.com/'],
  ['spoofed supplied URL', {url: 'https://chatgpt.com/'}, 'https://example.com/']
]) {
  test(`pair refuses ${name} without side effects`, async () => {
    const h = harness({tabUrl});
    const result = await send(h, pairing(overrides));
    assert.ok(result.error);
    assert.equal(h.requests.length, 0);
    assert.equal(h.storage.config, undefined);
    assert.deepEqual(h.alarms, []);
  });
}

test('pair binds only the confirmed second account to the actual ChatGPT tab', async () => {
  const h = harness();
  const result = await send(h, pairing());
  assert.equal(result.ok, true);
  assert.ok(h.tabLookups.length >= 1 && h.tabLookups.every(id => id === 7));
  assert.deepEqual(h.requests[0].body, {client_id: 'client-id', account: 'second', visible_model: 'Create image', input_protocol: 2});
  assert.equal(h.storage.config.account, 'second');
  assert.equal(h.storage.config.tabId, 7);
  assert.ok(h.alarms.some(args => args[0] === 'poll'));
});

test('pair refuses when the selected tab cannot confirm a fresh composer and visible model', async () => {
  const h = harness({inspection: {fresh: false, model: ''}});
  const result = await send(h, pairing());
  assert.ok(result.error);
  assert.equal(h.requests.length, 0);
  assert.equal(h.storage.config, undefined);
  assert.deepEqual(h.alarms, []);
});

test('owner-confirmed pairing reuses saved token and client id for the second tab only', async () => {
  const config = {token: 'synthetic-saved-token-' + 'x'.repeat(40), clientId: '123e4567-e89b-12d3-a456-426614174001', tabId: 6, account: 'second'};
  const h = harness();
  Object.assign(h.storage, {config});
  const response = await send(h, pairing({token: '', tabId: 7}));

  assert.ok(response.ok, response.error);
  assert.equal(h.requests[0].body.client_id, '123e4567-e89b-12d3-a456-426614174001');
  assert.equal(h.requests[0].body.account, 'second');
  assert.equal(h.requests[0].authorization, 'Bearer ' + config.token);
  assert.equal(h.storage.config.tabId, 7);
  assert.equal(h.storage.config.clientId, '123e4567-e89b-12d3-a456-426614174001');
});

test('saved key reuse still requires explicit owner confirmation', async () => {
  const config = {token: 'synthetic-saved-token-' + 'x'.repeat(40), clientId: '123e4567-e89b-12d3-a456-426614174001', tabId: 6, account: 'second'};
  const h = harness();
  Object.assign(h.storage, {config});
  const response = await send(h, pairing({token: '', confirmedAccount: false, tabId: 7}));

  assert.ok(response.error);
  assert.equal(h.requests.length, 0);
  assert.equal(h.storage.config, config);
});

test('disconnect refuses while a job is active and preserves pairing state', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active});
  Object.assign(h.storage, {active, config});
  const result = await send(h, {type: 'disconnect'});
  assert.ok(result.error);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['state']);
  assert.equal(h.storage.config, config);
  assert.equal(h.storage.active, active);
  assert.deepEqual(h.alarms, []);
});

test('poll recovers a terminal active job before claiming the next job', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, state: {state: 'complete'}, next: {job_id: 'job-2'}});
  Object.assign(h.storage, {active, config});

  h.fireAlarm();
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'state', 'next']);
  assert.equal(h.storage.lastJob.state, 'complete');
  assert.equal(h.storage.active.jobId, 'job-2');
  assert.equal(h.storage.active.tabId, 7);
});

test('poll keeps a nonterminal active job and does not claim another', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, state: {state: 'claimed'}});
  Object.assign(h.storage, {active, config});

  h.fireAlarm();
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'state']);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-prepare'), false);
  assert.equal(h.storage.active, active);
});

test('server-restart interruption is shown and never replays the claimed job', async () => {
  const active = {jobId: 'job-1', tabId: 7, job: {
    job_id: 'job-1', prompt: 'draw once', expected_model: 'Create image'
  }};
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const h = harness({active, state: {state: 'interrupted', error: 'Server restarted'}});
  Object.assign(h.storage, {active, config});
  h.fireAlarm();
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'state']);
  assert.equal(h.storage.active, undefined);
  assert.equal(h.storage.lastJob.state, 'interrupted');
  assert.match(JSON.stringify(h.storage.connection), /interrupted/);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-job'), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-prepare'), false);
  assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
});

test('poll reconnects a saved config after offline state and claims only after fresh heartbeat', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const persisted = {};
  const offline = harness({storage: persisted, failures: 1});
  Object.assign(offline.storage, {config});
  offline.fireAlarm();
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

  assert.equal(offline.storage.config, config);
  assert.equal(offline.requests.length, 1);
  assert.equal(offline.requests[0].url.endsWith('/heartbeat'), true);
  assert.equal(offline.requests[0].body.client_id, 'saved-client');
  assert.equal(offline.requests[0].body.account, 'second');
  assert.equal(offline.requests[0].body.tab_ready, true);
  assert.equal(offline.requests[0].body.input_protocol, 2);
  assert.equal(offline.requests[0].body.tab_idle, true);
  assert.equal(offline.requests[0].body.tab_error, '');
  assert.equal(offline.requests[0].body.worker_version, manifest.version);
  assert.equal(offline.requests[0].body.content_receiver, 'available');
  assert.equal(offline.requests[0].body.receiver_error, '');
  assert.equal(offline.requests.some(call => call.url.endsWith('/next')), false);

  const online = harness({next: {}});
  Object.assign(online.storage, {config: persisted.config});
  online.fireAlarm();
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

  assert.equal(online.storage.config, config);
  assert.deepEqual(online.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'next']);
  assert.equal(online.requests[0].body.client_id, 'saved-client');
  assert.equal(online.requests[1].body.client_id, 'saved-client');
  assert.equal(online.tabMessages.some(call => call.message.type === 'image-job'), false);
});

test('pair and disconnect refuse mutation while a heartbeat poll is in flight', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  await t.test('pair is blocked while heartbeat is pending', async () => {
    const h = harness({holdPath: '/heartbeat'});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.requests[0].url.endsWith('/heartbeat'), true);

    const response = await send(h, pairing({token: '', tabId: 7}));
    assert.ok(response.error);
    assert.equal(h.requests.some(call => call.url.endsWith('/pair')), false);
    assert.equal(h.storage.config, config);
    h.releaseNetwork();
  });

  await t.test('disconnect is blocked while heartbeat is pending', async () => {
    const h = harness({holdPath: '/heartbeat'});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.requests[0].url.endsWith('/heartbeat'), true);

    const response = await send(h, {type: 'disconnect'});
    assert.ok(response.error);
    assert.equal(h.storage.config, config);
    assert.equal(h.storage.connection, undefined);
    h.releaseNetwork();
  });
});

test('poll waits until in-flight pairing management releases its tab lookup', async () => {
  const h = harness({holdTabLookup: true});
  let pairResponse;
  const pairDone = new Promise(resolve => {
    h.receive(pairing(), {}, value => { pairResponse = value; resolve(value); });
  });
  for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(h.tabLookups, [7]);

  h.fireAlarm();
  for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.requests.length, 0);
  assert.equal(h.tabMessages.length, 0);

  h.releaseTabLookup();
  await pairDone;
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(pairResponse.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['pair', 'heartbeat', 'next']);
});

test('missing or wrong-domain paired tab heartbeats not-ready and never polls or prepares', async t => {
  for (const [name, options] of [
    ['missing tab', {tabExists: false}],
    ['wrong domain', {tabUrl: 'https://example.com/'}]
  ]) await t.test(name, async () => {
    const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
    const h = harness(options);
    Object.assign(h.storage, {config});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
    assert.equal(h.requests[0].url.endsWith('/heartbeat'), true);
    assert.equal(h.requests[0].body.tab_ready, false);
    assert.equal(h.requests[0].body.worker_version, manifest.version);
    assert.equal(h.requests[0].body.content_receiver, name === 'missing tab' ? 'tab_missing' : 'wrong_origin');
    assert.equal(h.requests[0].body.receiver_error, name === 'missing tab' ? 'tab_missing' : 'wrong_origin');
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-job'), false);
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-prepare'), false);
    assert.equal(h.storage.config, config);
    assert.equal(h.storage.connection.state, 'needs_tab');
  });
});

test('a missing saved tab rebinds only a single matching client marker', async t => {
  const clientId = '123e4567-e89b-12d3-a456-426614174001';
  const config = {token: 'synthetic-token', clientId, tabId: 7, account: 'second'};
  const chatgpt = id => ({id, url: 'https://chatgpt.com/'});

  await t.test('one matching tab becomes the paired tab and can receive work', async () => {
    const h = harness({tabExists: false, candidateTabs: [chatgpt(9)], identities: {9: clientId}, next: {}});
    Object.assign(h.storage, {config: {...config}});
    h.fireAlarm();
    for (let i = 0; i < 20 && h.storage.config.tabId !== 9; i++) await new Promise(resolve => setImmediate(resolve));

    assert.equal(h.storage.config.tabId, 9);
    assert.equal(h.storage.config.clientId, clientId);
    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.tab_recovery, 'rebound');
    assert.equal(heartbeat.chatgpt_tabs, 1);
    assert.equal(heartbeat.content_receiver, 'available');
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-identity' && call.id === 9), true);
    assert.equal(JSON.stringify(h.tabMessages).includes('https://'), false);
    assert.equal(h.storage.connection.state, 'ready');
  });

  await t.test('an unmarked open ChatGPT tab stays unpaired', async () => {
    const h = harness({tabExists: false, candidateTabs: [chatgpt(9)], identities: {9: ''}, next: {job_id: 'job-1'}});
    Object.assign(h.storage, {config: {...config}});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    assert.equal(h.storage.config.tabId, 7);
    assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-job' || call.message.type === 'image-prepare'), false);
    const heartbeat = h.requests[0].body;
    assert.equal(heartbeat.tab_recovery, 'unmatched');
    assert.equal(heartbeat.chatgpt_tabs, 1);
    assert.equal(heartbeat.content_receiver, 'tab_missing');
    assert.equal(h.storage.connection.state, 'needs_relink');
  });

  await t.test('two matching markers are ambiguous and are not adopted', async () => {
    const h = harness({tabExists: false, candidateTabs: [chatgpt(8), chatgpt(9)],
      identities: {8: clientId, 9: clientId}, next: {job_id: 'job-1'}});
    Object.assign(h.storage, {config: {...config}});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    assert.equal(h.storage.config.tabId, 7);
    assert.equal(h.requests[0].body.tab_recovery, 'unmatched');
    assert.equal(h.requests[0].body.chatgpt_tabs, 2);
    assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
  });

  await t.test('a different client marker is not adopted', async () => {
    const h = harness({tabExists: false, candidateTabs: [chatgpt(9)],
      identities: {9: '123e4567-e89b-12d3-a456-426614174099'}});
    Object.assign(h.storage, {config: {...config}});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    assert.equal(h.storage.config.tabId, 7);
    assert.equal(h.requests[0].body.tab_recovery, 'unmatched');
    assert.equal(h.storage.connection.state, 'needs_relink');
  });

  await t.test('tab replacement keeps the same pairing without a new code', async () => {
    const h = harness({next: {}});
    Object.assign(h.storage, {config: {...config}});
    await h.replaceTab(11, 7);
    for (let i = 0; i < 10 && h.storage.config.tabId !== 11; i++) await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.storage.config.tabId, 11);
    assert.equal(h.storage.config.token, config.token);
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.requests[0].body.tab_recovery, 'none');
    assert.equal(h.requests[0].body.content_receiver, 'available');
    assert.equal(h.tabLookups.at(-1), 11);
  });
});

test('old content replies remain available at protocol 0 and app-level content errors stay in tab_error', async t => {
  await t.test('old content protocol', async () => {
    const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
    const h = harness({inspection: {fresh: true, model: 'Create image'}, next: {}});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.worker_version, manifest.version);
    assert.equal(heartbeat.content_receiver, 'available');
    assert.equal(heartbeat.receiver_error, '');
    assert.equal(heartbeat.input_protocol, 0);
    assert.equal(heartbeat.tab_idle, null);
    assert.equal(heartbeat.tab_ready, true);
    assert.equal(h.requests.some(call => call.url.endsWith('/next')), true);
  });

  await t.test('new content app-level error', async () => {
    const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
    const contentError = 'Preserve the draft or running work. Nothing was submitted.';
    const h = harness({inspection: {error: contentError, input_protocol: 2, idle: false}, next: {}});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.worker_version, manifest.version);
    assert.equal(heartbeat.content_receiver, 'available');
    assert.equal(heartbeat.receiver_error, '');
    assert.equal(heartbeat.input_protocol, 2);
    assert.equal(heartbeat.tab_idle, false);
    assert.equal(heartbeat.tab_ready, false);
    assert.equal(heartbeat.tab_error, contentError);
    assert.equal(h.requests.some(call => call.url.endsWith('/next')), true);
  });
});

test('receiver failures are classified and never claim a queued job', async t => {
  const cases = [
    ['no receiver', {inspectError: 'Could not establish connection. Receiving end does not exist.'}, 'unavailable', 'no_receiver'],
    ['closed port', {inspectError: 'The message port closed before a response was received.'}, 'unavailable', 'port_closed'],
    ['unknown native error', {inspectError: 'native-private-error-should-not-leak'}, 'unavailable', 'message_failed'],
    ['invalid inspection reply', {inspection: {}}, 'invalid_reply', 'invalid_reply']
  ];
  for (const [name, options, receiver, errorCode] of cases) await t.test(name, async () => {
    const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
    const h = harness({...options, next: {job_id: 'job-1'}});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.worker_version, manifest.version);
    assert.equal(heartbeat.content_receiver, receiver);
    assert.equal(heartbeat.receiver_error, errorCode);
    assert.equal(heartbeat.tab_ready, false);
    assert.equal(heartbeat.input_protocol, 0);
    assert.equal(heartbeat.tab_idle, null);
    assert.equal(heartbeat.upload_dom, null);
    assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-prepare' || call.message.type === 'image-job'), false);
    assert.equal(JSON.stringify(heartbeat).includes('native-private-error-should-not-leak'), false);
  });
});

test('heartbeat forwards only an exact bounded upload DOM diagnostic and preserves unknown as null', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const settle = async h => {
    h.fireAlarm();
    for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve));
  };

  await t.test('valid exact-shape counts are forwarded', async () => {
    const diagnostic = uploadDom();
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 3, idle: true,
      upload_dom: diagnostic}, next: {}});
    Object.assign(h.storage, {config});
    await settle(h);
    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.deepEqual(heartbeat.upload_dom, diagnostic);
  });

  const invalid = [
    ['extra untrusted text', {...uploadDom(), page_url: 'https://private.invalid/path'}],
    ['missing field', Object.fromEntries(Object.entries(uploadDom()).slice(1))],
    ['boolean count', {...uploadDom(), file_inputs: true}],
    ['out-of-range count', {...uploadDom(), attachment_cards: 10001}],
    ['array', [uploadDom()]],
  ];
  for (const [name, upload_dom] of invalid) await t.test(name, async () => {
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 3, idle: true, upload_dom}, next: {}});
    Object.assign(h.storage, {config});
    await settle(h);
    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.upload_dom, null);
    assert.equal(JSON.stringify(heartbeat).includes('private.invalid'), false);
  });

  await t.test('no receiver leaves upload shape unknown instead of reporting fake zeroes', async () => {
    const h = harness({inspectError: 'Could not establish connection. Receiving end does not exist.', next: {}});
    Object.assign(h.storage, {config});
    await settle(h);
    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.content_receiver, 'unavailable');
    assert.equal(heartbeat.receiver_error, 'no_receiver');
    assert.equal(heartbeat.upload_dom, null);
  });
});

test('heartbeat forwards only bounded result DOM counts and a validated chat path', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const settle = async h => {
    h.fireAlarm();
    for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve));
  };

  await t.test('valid exact-shape counts and path are forwarded without page text', async () => {
    const diagnostic = resultDom();
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true,
      result_dom: diagnostic}, next: {}});
    Object.assign(h.storage, {config});
    await settle(h);

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.deepEqual(heartbeat.result_dom, diagnostic);
    assert.deepEqual(Object.keys(heartbeat.result_dom).sort(), Object.keys(diagnostic).sort());
    assert.equal(JSON.stringify(heartbeat.result_dom).includes('assistant reply'), false);
    assert.equal(JSON.stringify(heartbeat).includes('image_src'), false);
  });

  for (const [name, result_dom] of [
    ['extra page text', {...resultDom(), assistant_text: 'private conversation'}],
    ['invalid chat path', resultDom({chat_path: 'https://chatgpt.com/c/private'})],
    ['missing field', Object.fromEntries(Object.entries(resultDom()).slice(1))],
    ['boolean count', resultDom({assistant_images: true})],
    ['out-of-range count', resultDom({conversation_images: 10001})],
    ['array', [resultDom()]]
  ]) await t.test(name, async () => {
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true,
      result_dom}, next: {}});
    Object.assign(h.storage, {config});
    await settle(h);

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.result_dom, null);
    assert.equal(JSON.stringify(heartbeat).includes('private conversation'), false);
  });
});

test('heartbeat forwards only the bounded prompt DOM diagnostic and preserves unknown as null', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const settle = async h => {
    h.fireAlarm();
    for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve));
  };

  await t.test('valid exact-shape prompt and label metadata is forwarded', async () => {
    const diagnostic = promptDom();
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true,
      prompt_dom: diagnostic}, next: {}});
    Object.assign(h.storage, {config});
    await settle(h);

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.deepEqual(heartbeat.prompt_dom, diagnostic);
    assert.deepEqual(Object.keys(heartbeat.prompt_dom).sort(), Object.keys(diagnostic).sort());
    assert.equal(JSON.stringify(heartbeat).includes('private prompt text'), false);
  });

  const invalid = [
    ['extra raw prompt text field', {...promptDom(), prompt: 'private prompt text'}],
    ['out-of-range body length', promptDom({body_chars: 100001})],
    ['out-of-range label count', promptDom({label_count: 10001})],
    ['mismatched label count', promptDom({label_count: 0})],
    ['unrecognized tag', promptDom({labels: [{...promptDom().labels[0], tag: 'CUSTOM-ELEMENT'}]})],
    ['extra raw text in a label', promptDom({labels: [{...promptDom().labels[0], text: 'private prompt text'}]})],
    ['nonboolean label flag', promptDom({labels: [{...promptDom().labels[0], matched_chip: 'true'}]})],
    ['array', [promptDom()]]
  ];
  for (const [name, prompt_dom] of invalid) await t.test(name, async () => {
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true,
      prompt_dom}, next: {}});
    Object.assign(h.storage, {config});
    await settle(h);

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.prompt_dom, null);
    assert.equal(JSON.stringify(heartbeat).includes('private prompt text'), false);
  });

  await t.test('old inspection reply without prompt DOM remains unknown', async () => {
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true}, next: {}});
    Object.assign(h.storage, {config});
    await settle(h);

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.prompt_dom, null);
  });

  await t.test('unavailable old receiver leaves prompt DOM unknown', async () => {
    const h = harness({inspectError: 'Could not establish connection. Receiving end does not exist.', next: {}});
    Object.assign(h.storage, {config});
    await settle(h);

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.content_receiver, 'unavailable');
    assert.equal(heartbeat.prompt_dom, null);
  });
});

test('only a known no-receiver condition gets one exact-target reinjection attempt', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const noReceiver = 'Could not establish connection. Receiving end does not exist.';
  const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve)); };

  await t.test('reinjection restores protocol 2 and sends no content job', async () => {
    const h = harness({inspectError: noReceiver, scriptingAvailable: true,
      inspectionAfterInjection: {fresh: true, model: 'Create image', input_protocol: 2, idle: true}, next: {}});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    await settle();

    assert.deepEqual(JSON.parse(JSON.stringify(h.scriptInjections)), [{target: {tabId: 7}, files: ['content.js']}]);
    assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-inspect']);
    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.worker_version, manifest.version);
    assert.equal(heartbeat.content_receiver, 'available');
    assert.equal(heartbeat.receiver_error, '');
    assert.equal(heartbeat.input_protocol, 2);
    assert.equal(heartbeat.tab_idle, true);
    assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'next']);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
    assert.equal(h.tabMessages.some(call => ['image-prepare', 'image-job', 'image-delete'].includes(call.message.type)), false);
    assert.equal(JSON.stringify(h.scriptInjections).includes('synthetic-token'), false);
    assert.equal(JSON.stringify(h.scriptInjections).includes('saved-client'), false);
    assert.equal(h.reloadCalls, 0);
  });

  await t.test('content-level draft guard response survives reinjection', async () => {
    const reason = 'Preserve the draft or running work. Nothing was submitted.';
    const h = harness({inspectError: noReceiver, scriptingAvailable: true,
      inspectionAfterInjection: {error: reason, input_protocol: 2, idle: false}, next: {}});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    await settle();

    const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat')).body;
    assert.equal(heartbeat.content_receiver, 'available');
    assert.equal(heartbeat.receiver_error, '');
    assert.equal(heartbeat.input_protocol, 2);
    assert.equal(heartbeat.tab_idle, false);
    assert.equal(heartbeat.tab_ready, false);
    assert.equal(heartbeat.tab_error, reason);
    assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-inspect']);
    assert.equal(h.scriptInjections.length, 1);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
  });

  const cases = [
    ['missing scripting API', {inspectError: noReceiver}, 0],
    ['denied scripting API', {inspectError: noReceiver, scriptingAvailable: true, scriptingError: 'private native failure'}, 1],
    ['active job', {inspectError: noReceiver, scriptingAvailable: true, active: {jobId: 'old-job', tabId: 7}}, 0],
    ['wrong origin', {tabUrl: 'https://example.com/', inspectError: noReceiver, scriptingAvailable: true}, 0],
    ['redacted URL', {tabUrlRedacted: true, inspectError: noReceiver, scriptingAvailable: true}, 0],
    ['closed message port', {inspectError: 'The message port closed before a response was received.', scriptingAvailable: true}, 0]
  ];
  for (const [name, options, expectedInjections] of cases) await t.test(name, async () => {
    const h = harness({...options, next: {job_id: 'must-not-claim'}});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    await settle();

    assert.equal(h.scriptInjections.length, expectedInjections);
    assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
    assert.equal(h.tabMessages.some(call => ['image-prepare', 'image-job', 'image-delete'].includes(call.message.type)), false);
    assert.equal(JSON.stringify(h.requests).includes('private native failure'), false);
    assert.equal(h.reloadCalls, 0);
  });

  await t.test('a failed injection is not retried in this worker lifecycle', async () => {
    const h = harness({inspectError: noReceiver, scriptingAvailable: true, scriptingError: 'private native failure'});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    await settle();
    h.fireAlarm();
    await settle();

    assert.deepEqual(JSON.parse(JSON.stringify(h.scriptInjections)), [{target: {tabId: 7}, files: ['content.js']}]);
    assert.equal(h.requests.filter(call => call.url.endsWith('/heartbeat')).length, 2);
    assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
    assert.equal(JSON.stringify(h.requests).includes('private native failure'), false);
    assert.equal(h.reloadCalls, 0);
  });
});

test('a URL-redacted paired tab is checked through its content script before claiming', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {job_id: 'job-1', prompt: 'draw once', expected_model: 'Create image', mode: 'create'};
  const h = harness({tabUrlRedacted: true, inspection: {fresh: false, model: ''}, next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  assert.equal(h.requests[0].body.tab_ready, false);
  assert.equal(h.requests.filter(call => call.url.endsWith('/next')).length, 1);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-prepare', 'image-job']);
});

test('a URL-redacted tab without a responding content script is not claimed', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const h = harness({tabUrlRedacted: true, inspectError: 'Receiving end does not exist', next: {job_id: 'job-1'}});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat']);
  assert.equal(h.requests[0].body.tab_ready, false);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect']);
  assert.equal(h.storage.active, undefined);
  assert.equal(h.storage.connection.state, 'needs_tab');
});

test('a claimed job prepares the paired tab before dispatch and heartbeats readiness', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {job_id: 'job-1', prompt: 'draw once', expected_model: 'Create image', mode: 'create'};
  const h = harness({inspection: {fresh: false, model: ''}, next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'next', 'heartbeat']);
  assert.equal(h.requests[0].body.tab_ready, false);
  assert.equal(h.requests[0].body.input_protocol, 0);
  assert.equal(h.requests[1].body.client_id, 'saved-client');
  assert.equal(h.requests[2].body.tab_ready, true);
  assert.equal(h.requests[2].body.input_protocol, 2);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-prepare', 'image-job']);
  assert.equal(JSON.stringify(h.tabMessages[1].message), JSON.stringify({type: 'image-prepare', job}));
  assert.equal(JSON.stringify(h.tabMessages[2].message), JSON.stringify({type: 'image-job', job}));
  assert.equal(h.storage.active.jobId, 'job-1');
});

test('edit job delivers three ordered images once to the paired tab and keeps bytes out of storage and status', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = imageJob([referenceImage(1, 'source'), referenceImage(2, 'reference'), referenceImage(3, 'reference')]);
  const h = harness({inspection: {fresh: false, model: ''}, next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  const prepared = h.tabMessages.find(call => call.message.type === 'image-prepare');
  const dispatched = h.tabMessages.filter(call => call.message.type === 'image-job');
  assert.equal(prepared.id, config.tabId);
  assert.deepEqual(JSON.parse(JSON.stringify(prepared.message.job)), metadataOnly(job));
  assert.equal(dispatched.length, 1);
  assert.equal(dispatched[0].id, config.tabId);
  assert.deepEqual(JSON.parse(JSON.stringify(dispatched[0].message.job)), job);
  assert.deepEqual(dispatched[0].message.job.images.map(image => image.order), [1, 2, 3]);
  assert.deepEqual(dispatched[0].message.job.images.map(image => image.role), ['source', 'reference', 'reference']);
  assert.deepEqual(JSON.parse(JSON.stringify(h.storage.active.job)), metadataOnly(job));
  assert.equal(JSON.stringify(h.storage.active).includes('data_base64'), false);
  assert.equal(JSON.stringify(h.storage.active).includes('/private/'), false);
  assert.equal(JSON.stringify(h.requests.map(call => call.body)).includes(job.images[0].data_base64), false);

  h.storage.lastJob = {...job, images: job.images};
  const status = await send(h, {type: 'get-status', refresh: false});
  assert.equal(JSON.stringify(status.active), JSON.stringify({jobId: 'job-1'}));
  assert.equal(JSON.stringify(status).includes(job.images[0].data_base64), false);
  assert.equal(JSON.stringify(status).includes('/private/'), false);
  assert.equal(status.lastJob.images.length, 3);
  assert.equal(status.lastJob.images[0].data_base64, undefined);
  assert.equal(status.lastJob.prompt, undefined);
});

test('collect-only recovery dispatches metadata to the paired tab without preparing or submitting', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const recoveryChatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const job = metadataOnly({...imageJob([referenceImage(1, 'source'), referenceImage(2, 'reference')]),
    collect_only: true, preserve_chat: true, recovery_chat_path: recoveryChatPath, output_binding_revision: 2});
  const h = harness({inspection: {fresh: false, model: '', input_protocol: 4, idle: false}, next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'next']);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-collect']);
  const dispatched = h.tabMessages[1];
  assert.equal(dispatched.id, config.tabId);
  assert.deepEqual(JSON.parse(JSON.stringify(dispatched.message.job)), job);
  assert.equal(dispatched.message.job.collect_only, true);
  assert.equal(dispatched.message.job.preserve_chat, true);
  assert.equal(dispatched.message.job.recovery_chat_path, recoveryChatPath);
  assert.equal(dispatched.message.job.output_binding_revision, 2);
  assert.equal(JSON.stringify(h.storage.active.job).includes('data_base64'), false);
  assert.equal(h.tabMessages.some(call => ['image-prepare', 'image-job'].includes(call.message.type)), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
});

test('unsupported output-binding revisions are rejected before content submission or deletion', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const recoveryChatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const recoveryJob = metadataOnly({...imageJob([referenceImage(1, 'source'), referenceImage(2, 'reference')]),
    collect_only: true, preserve_chat: true, recovery_chat_path: recoveryChatPath, output_binding_revision: 1});
  const normalJob = {job_id: 'job-1', mode: 'create', prompt: 'draw once', expected_model: 'Create image',
    output_binding_revision: 2};

  for (const [name, job] of [['wrong recovery revision', recoveryJob], ['revision flag on normal job', normalJob]])
    await t.test(name, async () => {
      const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true}, next: job});
      Object.assign(h.storage, {config});
      h.fireAlarm();
      for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

      assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'next', 'result']);
      assert.match(h.requests.at(-1).body.error, /Unsupported output prompt binding revision/);
      assert.equal(h.tabMessages.some(call => ['image-prepare', 'image-job', 'image-collect', 'image-delete']
        .includes(call.message.type)), false);
      assert.equal(h.requests.some(call => call.url.endsWith('/cleanup')), false);
      assert.equal(h.storage.active, undefined);
    });
});

test('protocol-1 content refuses preflight without sending input bytes to content', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {...imageJob([referenceImage(1, 'source'), referenceImage(2, 'reference')]), preflight_only: true};
  const h = harness({
    inspection: {fresh: false, model: '', input_protocol: 1, idle: false},
    preparation: {fresh: true, model: 'Create image', input_protocol: 1, idle: true},
    next: job
  });
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  const heartbeats = h.requests.filter(call => call.url.endsWith('/heartbeat'));
  const result = h.requests.find(call => call.url.endsWith('/result'));
  assert.deepEqual(heartbeats.map(call => call.body.input_protocol), [1, 1]);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-prepare']);
  assert.deepEqual(JSON.parse(JSON.stringify(h.tabMessages[1].message.job)), metadataOnly(job));
  assert.equal(JSON.stringify(h.tabMessages).includes(job.images[0].data_base64), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-job'), false);
  assert.ok(result);
  assert.match(result.body.error, /no-Send preflight support/);
});

test('preflight preserves its flag and routes only an unsent readiness receipt', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {...imageJob([referenceImage(1, 'source'), referenceImage(2, 'reference')]), preflight_only: true};
  const receipt = {
    ...metadataOnly(job), state: 'complete', preflight_ready: true, submitted: false,
    generated: false, cleanup_status: 'not_requested', draft_note: 'Owned uploads remain unsent.'
  };
  const h = harness({
    inspection: {fresh: false, model: '', input_protocol: 2, idle: false},
    preparation: {fresh: true, model: 'Create image', input_protocol: 2, idle: true},
    next: job,
    responses: {result: receipt}
  });
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  const prepared = h.tabMessages.find(call => call.message.type === 'image-prepare');
  const dispatched = h.tabMessages.find(call => call.message.type === 'image-job');
  assert.ok(prepared, JSON.stringify({requests: h.requests, tabMessages: h.tabMessages, active: h.storage.active}));
  assert.equal(prepared.message.job.preflight_only, true);
  assert.equal(dispatched.message.job.preflight_only, true);
  assert.equal(h.storage.active.job.preflight_only, true);
  assert.equal(JSON.stringify(h.storage.active).includes('data_base64'), false);

  const wrongTab = await send(h, {type: 'image-result', jobId: job.job_id, preflightReady: true},
    {tab: {id: 8}, url: 'https://chatgpt.com/'});
  assert.ok(wrongTab.error);
  assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
  for (const invalidReceipt of [
    {preflightReady: true, imageBase64: 'eA=='},
    {preflightReady: true, chatPath: '/c/123e4567-e89b-12d3-a456-426614174000'},
  ]) {
    const rejected = await send(h, {type: 'image-result', jobId: job.job_id, ...invalidReceipt},
      {tab: {id: 7}, url: 'https://chatgpt.com/'});
    assert.match(rejected.error, /Preflight cannot accept generated media or cleanup/);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
  }

  const accepted = await send(h, {type: 'image-result', jobId: job.job_id, preflightReady: true},
    {tab: {id: 7}, url: 'https://chatgpt.com/'});
  assert.equal(accepted.ok, true);
  const resultRequest = h.requests.find(call => call.url.endsWith('/result'));
  assert.deepEqual(resultRequest.body, {client_id: 'saved-client', job_id: job.job_id, preflight_ready: true});
  assert.equal(h.requests.some(call => call.url.endsWith('/cleanup')), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);

  const status = await send(h, {type: 'get-status', refresh: false});
  assert.equal(status.connection.state, 'preflight_complete');
  assert.equal(status.lastJob.preflight_ready, true);
  assert.equal(status.lastJob.submitted, false);
  assert.equal(status.lastJob.generated, false);
  assert.equal(status.lastJob.cleanup_status, 'not_requested');
  assert.equal(status.lastJob.images[0].data_base64, undefined);
  assert.equal(JSON.stringify(status).includes('data_base64'), false);
});

test('cleared preflight requires protocol 3 and a matching native cleanup receipt', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {...imageJob([referenceImage(1, 'source'), referenceImage(2, 'reference')]),
    preflight_only: true, clear_preflight_uploads: true};
  const settle = async h => {
    h.fireAlarm();
    for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));
  };
  const activate = async (activeJob, response) => {
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 3, idle: true},
      next: activeJob, responses: response ? {result: response} : {}});
    Object.assign(h.storage, {config});
    await settle(h);
    return h;
  };

  await t.test('protocol 2 rejects opt-in cleanup before content dispatch', async () => {
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 2, idle: true}, next: job});
    Object.assign(h.storage, {config});
    await settle(h);

    const result = h.requests.find(call => call.url.endsWith('/result'));
    assert.match(result.body.error, /Protocol 3 is required/);
    assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect']);
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-job' || call.message.type === 'image-prepare'), false);
    assert.equal(JSON.stringify(h.tabMessages).includes(job.images[0].data_base64), false);
  });

  await t.test('missing opt-in clearing receipt is rejected without a server result', async () => {
    const h = await activate(job);
    assert.equal(h.storage.active.job.clear_preflight_uploads, true);
    const rejected = await send(h, {type: 'image-result', jobId: job.job_id, preflightReady: true},
      {tab: {id: 7}, url: 'https://chatgpt.com/'});
    assert.match(rejected.error, /Verified preflight upload clearing receipt is required/);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
    assert.equal(h.storage.active.job.clear_preflight_uploads, true);
  });

  await t.test('unsolicited clearing receipt is rejected for a default preflight', async () => {
    const defaultJob = {...imageJob([referenceImage(1, 'source')]), preflight_only: true};
    const h = await activate(defaultJob);
    const rejected = await send(h, {type: 'image-result', jobId: defaultJob.job_id,
      preflightReady: true, preflightUploadsCleared: true}, {tab: {id: 7}, url: 'https://chatgpt.com/'});
    assert.match(rejected.error, /Preflight upload clearing was not requested/);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
  });

  await t.test('unsolicited clearing receipt is rejected for image generation', async () => {
    const generation = imageJob([referenceImage(1, 'source')]);
    const active = {jobId: generation.job_id, tabId: 7, job: metadataOnly(generation)};
    const h = harness({active});
    Object.assign(h.storage, {config, active});
    const rejected = await send(h, {type: 'image-result', jobId: generation.job_id,
      imageBase64: 'eA==', preflightUploadsCleared: true}, {tab: {id: 7}, url: 'https://chatgpt.com/'});
    assert.match(rejected.error, /Preflight upload clearing was not requested/);
    assert.equal(h.requests.length, 0);
  });

  await t.test('matching cleared receipt is mirrored into the server result and status', async () => {
    const receipt = {job_id: job.job_id, state: 'complete', preflight_ready: true,
      preflight_uploads_cleared: true, submitted: false, generated: false, cleanup_status: 'not_requested'};
    const h = await activate(job, receipt);
    const dispatched = h.tabMessages.find(call => call.message.type === 'image-job');
    assert.equal(dispatched.message.job.clear_preflight_uploads, true);
    assert.equal(JSON.stringify(h.storage.active).includes('data_base64'), false);
    const accepted = await send(h, {type: 'image-result', jobId: job.job_id,
      preflightReady: true, preflightUploadsCleared: true}, {tab: {id: 7}, url: 'https://chatgpt.com/'});
    assert.equal(accepted.ok, true);
    const result = h.requests.find(call => call.url.endsWith('/result'));
    assert.deepEqual(result.body, {client_id: 'saved-client', job_id: job.job_id,
      preflight_ready: true, preflight_uploads_cleared: true});
    assert.equal(h.requests.some(call => call.url.endsWith('/cleanup')), false);
    const status = await send(h, {type: 'get-status', refresh: false});
    assert.equal(status.lastJob.preflight_uploads_cleared, true);
  });
});

test('protocols 0 through 3 preserve ordinary create-job dispatch', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  for (const protocol of [0, 1, 2, 3]) await t.test(`protocol ${protocol}`, async () => {
    const job = {job_id: 'job-1', mode: 'create', prompt: 'draw once', expected_model: 'Create image'};
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: protocol, idle: true}, next: job});
    Object.assign(h.storage, {config});

    h.fireAlarm();
    for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

    assert.equal(h.requests.find(call => call.url.endsWith('/heartbeat')).body.input_protocol, protocol);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
    assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-job']);
    assert.deepEqual(JSON.parse(JSON.stringify(h.tabMessages[1].message)), {type: 'image-job', job});
    assert.equal(h.tabMessages.filter(call => call.message.type === 'image-job').length, 1);
  });
});

test('protocol 3 still dispatches an ordinary image job with its required bytes', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = imageJob([referenceImage(1, 'source')]);
  const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 3, idle: true}, next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  assert.equal(h.requests.find(call => call.url.endsWith('/heartbeat')).body.input_protocol, 3);
  assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-job']);
  assert.deepEqual(JSON.parse(JSON.stringify(h.tabMessages[1].message.job)), job);
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-job').length, 1);
  assert.equal(JSON.stringify(h.storage.active).includes('data_base64'), false);
});

test('protocol-4 heartbeat dispatches inspected cleanup resume metadata without a second upload', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = metadataOnly(cleanupOnlyPreflight([referenceImage(1, 'source'), referenceImage(2, 'reference')]));
  job.preflight_cleanup_resumed = true;
  for (const image of job.images) image.name = image.name.replace('.png', '(1).png');
  const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true}, next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  const heartbeat = h.requests.find(call => call.url.endsWith('/heartbeat'));
  assert.equal(heartbeat.body.input_protocol, 4);
  assert.equal(heartbeat.body.tab_ready, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'next']);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-job']);
  const dispatched = h.tabMessages.filter(call => call.message.type === 'image-job');
  assert.equal(dispatched.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(dispatched[0].message.job)), job);
  assert.equal(h.storage.active.job.preflight_only, true);
  assert.equal(h.storage.active.job.clear_preflight_uploads, true);
  assert.equal(h.storage.active.job.preflight_cleanup_only, true);
  assert.equal(h.storage.active.job.preflight_cleanup_resumed, true);
  assert.deepEqual(JSON.parse(JSON.stringify(h.storage.active.job)), job);
  for (const value of [h.storage.active, h.tabMessages, h.requests]) {
    assert.equal(JSON.stringify(value).includes('data_base64'), false);
    assert.equal(JSON.stringify(value).includes('/private/'), false);
  }
});

test('protocol 3 refuses cleanup-only preflight before content dispatch', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = metadataOnly(cleanupOnlyPreflight([referenceImage(1, 'source')]));
  const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 3, idle: true}, next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  assert.equal(h.requests.find(call => call.url.endsWith('/heartbeat')).body.input_protocol, 3);
  const result = h.requests.find(call => call.url.endsWith('/result'));
  assert.match(result.body.error, /Protocol 4 is required/);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-prepare' || call.message.type === 'image-job'), false);
  assert.equal(h.storage.active, undefined);
});

test('cleanup-only preflight rejects malformed flags, empty images, and byte reuploads', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const fullJob = cleanupOnlyPreflight([referenceImage(1, 'source')]);
  const cases = [
    ['without preflight_only', metadataOnly({...fullJob, preflight_only: false})],
    ['non-boolean preflight_only', metadataOnly({...fullJob, preflight_only: 'true'})],
    ['without clear_preflight_uploads', metadataOnly({...fullJob, clear_preflight_uploads: false})],
    ['non-boolean clear_preflight_uploads', metadataOnly({...fullJob, clear_preflight_uploads: 'true'})],
    ['non-boolean cleanup flag', {...metadataOnly(fullJob), preflight_cleanup_only: 'true'}],
    ['non-boolean resume flag', {...metadataOnly(fullJob), preflight_cleanup_resumed: 'true'}],
    ['resume without cleanup-only', {...metadataOnly(fullJob), preflight_cleanup_only: false, preflight_cleanup_resumed: true}],
    ['empty images', metadataOnly(cleanupOnlyPreflight([]))],
    ['image bytes reuploaded for cleanup-only', fullJob],
    ['ordinary upload without valid bytes', metadataOnly(imageJob([referenceImage(1, 'source')]))]
  ];

  for (const [name, job] of cases) await t.test(name, async () => {
    const h = harness({next: job});
    Object.assign(h.storage, {config});

    h.fireAlarm();
    for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

    const result = h.requests.find(call => call.url.endsWith('/result'));
    assert.ok(result?.body.error, JSON.stringify(h.requests));
    assert.equal(h.storage.active, undefined);
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-prepare' || call.message.type === 'image-job'), false);
  });
});

test('cleanup-only preflight accepts only a matching, typed upload-clear receipt', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = metadataOnly(cleanupOnlyPreflight([referenceImage(1, 'source')]));
  const activate = async () => {
    const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true}, next: job,
      responses: {result: {job_id: job.job_id, state: 'complete', preflight_ready: true,
        preflight_uploads_cleared: true, submitted: false, generated: false, cleanup_status: 'not_requested'}}});
    Object.assign(h.storage, {config});
    h.fireAlarm();
    for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.storage.active.job.preflight_cleanup_only, true);
    return h;
  };

  await t.test('wrong tab cannot submit the clear receipt', async () => {
    const h = await activate();
    const response = await send(h, {type: 'image-result', jobId: job.job_id,
      preflightReady: true, preflightUploadsCleared: true}, {tab: {id: 8}, url: 'https://chatgpt.com/'});
    assert.match(response.error, /Result is not from the paired job\/tab/);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
    assert.equal(h.storage.active.job.preflight_cleanup_only, true);
  });

  await t.test('clear receipt without readiness is rejected', async () => {
    const h = await activate();
    const response = await send(h, {type: 'image-result', jobId: job.job_id,
      preflightReady: false, preflightUploadsCleared: true}, {tab: {id: 7}, url: 'https://chatgpt.com/'});
    assert.match(response.error, /Preflight cannot accept generated media or cleanup/);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
    assert.equal(h.storage.active.job.preflight_cleanup_only, true);
  });

  for (const [name, receipt, pattern] of [
    ['missing', undefined, /Verified preflight upload clearing receipt is required/],
    ['false', false, /Verified preflight upload clearing receipt is required/],
    ['non-boolean', 'true', /Invalid preflight clearing receipt/]
  ]) await t.test(`${name} receipt is rejected without consuming the active job`, async () => {
    const h = await activate();
    const message = {type: 'image-result', jobId: job.job_id, preflightReady: true};
    if (receipt !== undefined) message.preflightUploadsCleared = receipt;
    const response = await send(h, message, {tab: {id: 7}, url: 'https://chatgpt.com/'});
    assert.match(response.error, pattern);
    assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
    assert.equal(h.storage.active.job.preflight_cleanup_only, true);
  });

  await t.test('confirmed receipt is sent to the server without generated media', async () => {
    const h = await activate();
    const response = await send(h, {type: 'image-result', jobId: job.job_id,
      preflightReady: true, preflightUploadsCleared: true}, {tab: {id: 7}, url: 'https://chatgpt.com/'});
    assert.equal(response.ok, true);
    const result = h.requests.find(call => call.url.endsWith('/result'));
    assert.deepEqual(result.body, {client_id: config.clientId, job_id: job.job_id,
      preflight_ready: true, preflight_uploads_cleared: true});
    assert.equal(h.requests.some(call => call.url.endsWith('/cleanup')), false);
    assert.equal(h.storage.active, undefined);
    assert.equal(h.storage.lastJob.preflight_uploads_cleared, true);
    assert.equal(JSON.stringify(result.body).includes('image_base64'), false);
  });
});

test('interrupted preflight is never replayed after worker restart', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {...imageJob([referenceImage(1, 'reference')]), preflight_only: true};
  const active = {jobId: job.job_id, tabId: config.tabId, job: metadataOnly(job)};
  const h = harness({active, state: {state: 'interrupted', error: 'Server restarted'}});
  Object.assign(h.storage, {config, active});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'state']);
  assert.equal(h.storage.active, undefined);
  assert.equal(h.storage.lastJob.state, 'interrupted');
  assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-prepare'), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-job'), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
});

test('failed-upload cleanup keeps the original failed receipt and reports an empty draft', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = metadataOnly(cleanupOnlyPreflight([referenceImage(1, 'reference')]));
  job.mode = 'create';
  const receipt = {job_id: job.job_id, state: 'failed', uploads_cleared: true,
    submitted: false, generated: false, cleanup_status: 'not_requested'};
  const h = harness({inspection: {fresh: true, model: 'Create image', input_protocol: 4, idle: true},
    next: job, responses: {result: receipt}});
  Object.assign(h.storage, {config});
  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));
  const result = await send(h, {type: 'image-result', jobId: job.job_id,
    preflightReady: true, preflightUploadsCleared: true}, {tab: {id: 7}, url: 'https://chatgpt.com/'});
  assert.equal(result.ok, true);
  assert.deepEqual(h.storage.lastJob, receipt);
  assert.equal(h.storage.active, undefined);
  assert.match(h.storage.connection.detail, /แท็บว่าง.*ไม่ได้เจนภาพ/);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
});

test('create mode accepts three uniquely named reference-only images without a source role', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {...imageJob([referenceImage(1, 'reference'), referenceImage(2, 'reference'), referenceImage(3, 'reference')]), mode: 'create'};
  for (const image of job.images) image.name = image.name.replace('.png', '-0123456789abcdef0123456789abcdef.png');
  const h = harness({next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  const dispatched = h.tabMessages.filter(call => call.message.type === 'image-job');
  assert.equal(dispatched.length, 1);
  assert.equal(dispatched[0].id, config.tabId);
  assert.equal(JSON.stringify(dispatched[0].message.job), JSON.stringify(job));
});

test('malformed edit image payloads fail before content dispatch', async t => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const cases = [
    ['nonsequential order', images => { images[1].order = 3; }],
    ['invalid role', images => { images[1].role = 'background'; }],
    ['unsafe local filename', images => { images[0].name = '../../source.png'; }],
    ['duplicate alias is cleanup-only', images => { images[0].name = 'input-001(1).png'; }],
    ['edit without source image', images => { images.forEach(image => { image.role = 'reference'; }); }]
  ];
  for (const [name, mutate] of cases) await t.test(name, async () => {
    const images = [referenceImage(1, 'source'), referenceImage(2, 'reference')];
    mutate(images);
    const h = harness({next: imageJob(images)});
    Object.assign(h.storage, {config});

    h.fireAlarm();
    for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

    assert.equal(h.tabMessages.some(call => ['image-prepare', 'image-job'].includes(call.message.type)), false);
    assert.equal(h.storage.active, undefined);
    assert.equal(h.requests.filter(call => call.url.endsWith('/result')).length, 1);
  });
});

test('total image payload above 8 MiB is rejected without dispatch', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const images = [referenceImage(1, 'source', Buffer.alloc(4 * 1024 * 1024)),
    referenceImage(2, 'reference', Buffer.alloc(4 * 1024 * 1024 + 1))];
  const h = harness({next: imageJob(images)});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  assert.equal(h.tabMessages.some(call => ['image-prepare', 'image-job'].includes(call.message.type)), false);
  assert.equal(h.storage.active, undefined);
  assert.equal(h.requests.filter(call => call.url.endsWith('/result')).length, 1);
});

test('a payload-bearing active edit is never replayed after worker restart and rejects another tab result', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = metadataOnly(imageJob([referenceImage(1, 'source'), referenceImage(2, 'reference')]));
  const active = {jobId: job.job_id, tabId: config.tabId, job};
  const h = harness({active, config, state: {state: 'claimed', expected_model: 'Create image'}, next: {}});
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  const wrongTab = await send(h, {type: 'image-result', jobId: job.job_id, imageBase64: 'result'},
    {tab: {id: 8}, url: 'https://chatgpt.com/c/123e4567-e89b-12d3-a456-426614174000'});
  assert.ok(wrongTab.error);
  assert.equal(h.requests.some(call => call.url.endsWith('/result')), false);
  assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
  assert.equal(h.tabMessages.some(call => ['image-prepare', 'image-job'].includes(call.message.type)), false);
});

test('a not-ready paired tab is not prepared when there is no queued job', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const h = harness({inspection: {fresh: false, model: ''}, next: {}});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'next']);
  assert.equal(h.requests[0].body.tab_ready, false);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect']);
  assert.equal(h.storage.active, undefined);
});

test('preparation failure fails the claimed job as not submitted and does not replay it', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {job_id: 'job-1', prompt: 'draw once', expected_model: 'Create image'};
  const h = harness({inspection: {fresh: false, model: ''}, next: job, prepareError: 'Composer unavailable'});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  const result = h.requests.find(call => call.url.endsWith('/result'));
  assert.ok(result);
  assert.equal(result.body.job_id, 'job-1');
  assert.match(result.body.error, /Not submitted/);
  assert.equal(h.requests.filter(call => call.url.endsWith('/next')).length, 1);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-job'), false);
  assert.equal(h.storage.active, undefined);
  assert.ok(h.storage.lastJob);
});

test('get-status is sanitized and triggers a reconnect poll', async () => {
  const config = {token: 'synthetic-secret', clientId: 'private-client-id', tabId: 7, account: 'second'};
  const h = harness();
  Object.assign(h.storage, {config});
  const status = await send(h, {type: 'get-status'});

  const serialized = JSON.stringify(status);
  assert.ok(status);
  assert.equal(serialized.includes('synthetic-secret'), false);
  assert.equal(serialized.includes('private-client-id'), false);
  assert.match(serialized, /second/);
  assert.match(serialized, /7/);
  assert.equal(h.requests.some(call => call.url.endsWith('/heartbeat')), true);
});

test('cached get-status skips polling for popup storage-change updates', async () => {
  const config = {token: 'synthetic-secret', clientId: 'private-client-id', tabId: 7, account: 'second'};
  const h = harness();
  Object.assign(h.storage, {config, connection: {state: 'offline'}});
  const status = await send(h, {type: 'get-status', refresh: false});

  assert.equal(status.connection.state, 'offline');
  assert.equal(h.requests.length, 0);
  assert.equal(JSON.stringify(status).includes('synthetic-secret'), false);
});

test('401 marks pairing required while transient outage is offline without deleting config', async t => {
  for (const [name, options, stateLabel] of [
    ['unauthorized', {httpError: 401}, 'needs_pairing'],
    ['offline', {failures: 1}, 'offline']
  ]) await t.test(name, async () => {
    const config = {token: 'synthetic-secret', clientId: 'saved-client', tabId: 7, account: 'second'};
    const h = harness(options);
    Object.assign(h.storage, {config});
    h.fireAlarm();
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    assert.equal(h.storage.config, config);
    assert.match(JSON.stringify(h.storage.connection), new RegExp(stateLabel));
  });
});

test('pair refuses to replace an active job without contacting the bridge', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const h = harness({active});
  const result = await send(h, pairing());
  assert.ok(result.error);
  assert.equal(h.requests.length, 0);
  assert.equal(h.storage.active, active);
  assert.equal(h.storage.config, undefined);
  assert.deepEqual(h.alarms, []);
});

test('saved paired image opens Delete confirmation and records owner-confirmed deletion', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, responses: {result: {state: 'complete'}, cleanup: [
    {state: 'complete', cleanup_status: 'confirmation_required'},
    {state: 'complete', cleanup_status: 'deleted'}
  ]}});
  Object.assign(h.storage, {active, config});
  const {message, sender} = pairedImageResult();

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result', 'cleanup', 'cleanup']);
  assert.equal(h.requests[0].body.cleanup_pending, true);
  assert.equal(h.requests[0].body.chat_path, message.chatPath);
  assert.equal(h.requests[1].body.cleanup_status, 'confirmation_required');
  assert.equal(h.requests[2].body.cleanup_status, 'deleted');
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-delete').length, 1);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-archive'), false);
  assert.equal(h.tabMessages[0].id, 7);
  assert.equal(h.tabMessages[0].message.chatPath, message.chatPath);
  assert.equal(h.storage.lastJob.cleanup_status, 'deleted');
  assert.equal(h.storage.active, undefined);

  const duplicate = await send(h, message, sender);
  assert.ok(duplicate.error);
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-delete').length, 1);
});

test('automatic saved-chat deletion follows requested confirmation through the existing native handshake', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, autoDeleteConfirmation: true, responses: {
    result: {state: 'complete'},
    cleanup: [
      {state: 'complete', cleanup_status: 'confirmation_required', cleanup_confirmation: 'requested'},
      {state: 'complete', cleanup_status: 'deleted'}
    ],
    'cleanup-confirmation': {confirmed: true}
  }});
  Object.assign(h.storage, {active, config});
  const {message, sender} = pairedImageResult();

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)),
    ['result', 'cleanup', 'cleanup-confirmation', 'cleanup']);
  assert.equal(h.requests[1].body.cleanup_status, 'confirmation_required');
  assert.deepEqual(h.requests[2].body, {client_id: 'client', job_id: 'job-1'});
  assert.equal(h.requests[3].body.cleanup_status, 'deleted');
  assert.equal(h.requests.some(call => call.url.endsWith('/agentconfirm')), false);
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-delete').length, 1);
  assert.equal(h.storage.lastJob.cleanup_status, 'deleted');
});

test('image-delete-prompt requires the currently finishing paired job', async t => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const prompt = {type: 'image-delete-prompt', jobId: 'job-1'};
  const sender = {tab: {id: 7}, url: 'https://chatgpt.com/c/123e4567-e89b-12d3-a456-426614174000'};

  await t.test('rejects before image-result has entered finishing', async () => {
    const h = harness({active});
    Object.assign(h.storage, {active, config});
    const response = await send(h, prompt, sender);
    assert.ok(response.error);
    assert.equal(h.requests.length, 0);
  });

  await t.test('rejects a different job or tab while finishing', async () => {
    const h = harness({active, holdPath: '/result', responses: {result: {state: 'complete'}}});
    Object.assign(h.storage, {active, config});
    const {message: resultMessage, sender: resultSender} = pairedImageResult();
    let completeResult;
    const completion = new Promise(resolve => h.receive(resultMessage, resultSender, value => { completeResult = value; resolve(value); }));
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    const wrongJob = await send(h, {...prompt, jobId: 'job-2'}, sender);
    const wrongTab = await send(h, prompt, {...sender, tab: {id: 8}});
    assert.ok(wrongJob.error);
    assert.ok(wrongTab.error);
    assert.equal(h.requests.filter(call => call.url.endsWith('/cleanup')).length, 0);

    h.releaseNetwork();
    await completion;
    assert.equal(completeResult.ok, true);
  });
});

test('image-delete-confirmation forwards only for the currently finishing paired job', async t => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const confirmation = {type: 'image-delete-confirmation', jobId: 'job-1'};
  const sender = {tab: {id: 7}, url: 'https://chatgpt.com/c/123e4567-e89b-12d3-a456-426614174000'};

  await t.test('rejects when unpaired or outside finishing', async () => {
    const unpaired = harness();
    assert.ok((await send(unpaired, confirmation, sender)).error);
    assert.equal(unpaired.requests.length, 0);

    const idle = harness({active});
    Object.assign(idle.storage, {active, config});
    assert.ok((await send(idle, confirmation, sender)).error);
    assert.equal(idle.requests.length, 0);
  });

  for (const [name, message, source] of [
    ['wrong job', {...confirmation, jobId: 'job-2'}, sender],
    ['wrong tab', confirmation, {...sender, tab: {id: 8}}],
    ['wrong origin', confirmation, {...sender, url: 'https://example.com/'}]
  ]) await t.test(`rejects ${name} while finishing`, async () => {
    const h = harness({active, holdPath: '/result', responses: {result: {state: 'complete'}}});
    Object.assign(h.storage, {active, config});
    const {message: resultMessage, sender: resultSender} = pairedImageResult();
    const completion = new Promise(resolve => h.receive(resultMessage, resultSender, resolve));
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    assert.ok((await send(h, message, source)).error);
    assert.equal(h.requests.some(call => call.url.endsWith('/cleanup-confirmation')), false);
    h.releaseNetwork();
    await completion;
  });

  await t.test('forwards and returns false or true unchanged without owning UI completion', async () => {
    for (const confirmed of [false, true]) {
      const result = {confirmed};
      const h = harness({active, holdPath: '/result', responses: {
        result: {state: 'complete'}, 'cleanup-confirmation': result
      }});
      Object.assign(h.storage, {active, config});
      const {message: resultMessage, sender: resultSender} = pairedImageResult();
      const completion = new Promise(resolve => h.receive(resultMessage, resultSender, resolve));
      for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

      assert.deepEqual(await send(h, confirmation, sender), result);
      const forwarded = h.requests.find(call => call.url.endsWith('/cleanup-confirmation'));
      assert.deepEqual(forwarded.body, {client_id: 'client', job_id: 'job-1'});
      assert.equal(h.requests.filter(call => call.url.endsWith('/cleanup-confirmation')).length, 1);
      assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
      h.releaseNetwork();
      await completion;
    }
  });

  await t.test('does not retry a failed confirmation request', async () => {
    const h = harness({active, holdPath: '/result', failPaths: ['/cleanup-confirmation'],
      responses: {result: {state: 'complete'}}});
    Object.assign(h.storage, {active, config});
    const {message: resultMessage, sender: resultSender} = pairedImageResult();
    const completion = new Promise(resolve => h.receive(resultMessage, resultSender, resolve));
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));

    assert.match((await send(h, confirmation, sender)).error, /offline/);
    assert.equal(h.requests.filter(call => call.url.endsWith('/cleanup-confirmation')).length, 1);
    h.releaseNetwork();
    await completion;
    assert.equal(h.requests.filter(call => call.url.endsWith('/cleanup-confirmation')).length, 1);
  });
});

test('image-result only opens Delete confirmation after a successful save with a valid chat path', async t => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  for (const [name, options, resultBody, expectedCleanupPending] of [
    ['failed save', {}, {state: 'failed'}, true],
    ['content error', {}, {state: 'failed'}, undefined],
    ['legacy result without chat path', {message: {chatPath: undefined}}, {state: 'complete'}, false],
    ['invalid chat path', {message: {chatPath: '/'}}, {state: 'complete'}, false]
  ]) await t.test(name, async () => {
    const h = harness({active, responses: {result: resultBody}});
    Object.assign(h.storage, {active, config});
    const overrides = name === 'content error' ? {error: 'Image download failed'} : options.message;
    const {message: validMessage, sender: validSender} = pairedImageResult(overrides);
    const sender = validSender;

    const response = await send(h, validMessage, sender);

    assert.equal(response.ok, true);
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
    assert.equal(h.requests.some(call => call.url.endsWith('/cleanup')), false);
    assert.equal(h.requests[0].body.cleanup_pending, expectedCleanupPending);
  });
});

test('multiple generated outputs use images_base64 and never trigger chat cleanup', async () => {
  const active = {jobId: 'job-1', tabId: 7, job: {job_id: 'job-1'}};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, responses: {result: {state: 'complete'}}});
  Object.assign(h.storage, {active, config});
  const imagesBase64 = ['cG5nMQ==', 'cG5nMg=='];
  const {message, sender} = pairedImageResult({imagesBase64});

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result']);
  assert.deepEqual(h.requests[0].body.images_base64, imagesBase64);
  assert.equal(h.requests[0].body.image_base64, undefined);
  assert.equal(h.requests[0].body.cleanup_pending, false);
  assert.equal(h.requests[0].body.chat_path, message.chatPath);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
});

test('single-output recovery saves the image and preserves the existing chat', async () => {
  const recoveryChatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const active = {jobId: 'job-1', tabId: 7, job: {job_id: 'job-1', collect_only: true,
    preserve_chat: true, recovery_chat_path: recoveryChatPath}};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, responses: {result: {state: 'complete'}}});
  Object.assign(h.storage, {active, config});
  const {message, sender} = pairedImageResult({chatPath: recoveryChatPath});

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result']);
  assert.equal(h.requests[0].body.image_base64, message.imageBase64);
  assert.equal(h.requests[0].body.images_base64, undefined);
  assert.equal(h.requests[0].body.chat_path, recoveryChatPath);
  assert.equal(h.requests[0].body.cleanup_pending, false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
});

test('successful recovery forwards prompt binding metadata and never deletes the chat', async () => {
  const recoveryChatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const active = {jobId: 'job-1', tabId: 7, job: {job_id: 'job-1', collect_only: true,
    preserve_chat: true, recovery_chat_path: recoveryChatPath}};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, responses: {result: {state: 'complete'}}});
  Object.assign(h.storage, {active, config});
  const promptBinding = {root_match: false, exact_matching_descendant_count: 1,
    expected_chars: 487, observed_chars: 502};
  const {message, sender} = pairedImageResult({chatPath: recoveryChatPath, promptBinding});

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result']);
  assert.deepEqual(h.requests[0].body.prompt_binding, promptBinding);
  assert.equal(h.requests[0].body.cleanup_pending, false);
  assert.equal(h.requests.some(call => call.url.endsWith('/cleanup')), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
});

test('failed recovery forwards prompt binding metadata and never deletes the chat', async () => {
  const recoveryChatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const active = {jobId: 'job-1', tabId: 7, job: {job_id: 'job-1', collect_only: true,
    preserve_chat: true, recovery_chat_path: recoveryChatPath}};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, responses: {result: {state: 'failed'}}});
  Object.assign(h.storage, {active, config});
  const promptBinding = {root_match: false, exact_matching_descendant_count: 0,
    expected_chars: 487, observed_chars: 1284};
  const {message, sender} = pairedImageResult({chatPath: undefined, imageBase64: undefined,
    promptBinding, error: 'Existing submitted-job recovery failed. Prompt mismatch.'});

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result']);
  assert.deepEqual(h.requests[0].body, {client_id: config.clientId, job_id: active.jobId,
    error: message.error, prompt_binding: promptBinding});
  assert.equal(h.requests.some(call => call.url.endsWith('/cleanup')), false);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
});

test('preflight rejects multiple generated outputs without sending a result or cleanup request', async () => {
  const active = {jobId: 'job-1', tabId: 7, job: {job_id: 'job-1', preflight_only: true}};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active});
  Object.assign(h.storage, {active, config});
  const {message, sender} = pairedImageResult({preflightReady: true, imageBase64: undefined,
    imagesBase64: ['cG5nMQ==', 'cG5nMg=='], chatPath: undefined});

  const response = await send(h, message, sender);

  assert.match(response.error, /Preflight cannot accept generated media or cleanup/);
  assert.equal(h.requests.length, 0);
  assert.equal(h.tabMessages.some(call => call.message.type === 'image-delete'), false);
  assert.equal(h.storage.active, active);
});

test('valid result chat path opens Delete confirmation when sender URL still names the previous SPA chat', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, responses: {
    result: {state: 'complete'}, cleanup: [
      {state: 'complete', cleanup_status: 'confirmation_required'},
      {state: 'complete', cleanup_status: 'deleted'}
    ]
  }});
  Object.assign(h.storage, {active, config});
  const {message, sender: pairedSender} = pairedImageResult();
  const sender = {...pairedSender, url: 'https://chatgpt.com/c/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'};

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.equal(h.requests[0].body.cleanup_pending, true);
  assert.equal(h.requests[0].body.chat_path, message.chatPath);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result', 'cleanup', 'cleanup']);
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-delete').length, 1);
  assert.equal(h.tabMessages[0].message.chatPath, message.chatPath);
  assert.equal(h.requests[1].body.cleanup_status, 'confirmation_required');
  assert.equal(h.requests[2].body.cleanup_status, 'deleted');
});

test('delete failure preserves saved image success and records cleanup failure once', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, deleteResponse: {error: 'Owner cancelled'}, responses: {
    result: {state: 'complete'}, cleanup: [
      {state: 'complete', cleanup_status: 'confirmation_required'},
      {state: 'complete', cleanup_status: 'failed'}
    ]
  }});
  Object.assign(h.storage, {active, config});
  const {message, sender} = pairedImageResult();

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result', 'cleanup', 'cleanup']);
  assert.equal(h.requests[1].body.cleanup_status, 'confirmation_required');
  assert.equal(h.requests[2].body.cleanup_status, 'failed');
  assert.match(h.requests[2].body.error, /Owner cancelled/);
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-delete').length, 1);
  assert.equal(h.storage.lastJob.state, 'complete');
  assert.equal(h.storage.active, undefined);
});

test('a lost confirmation or cleanup receipt stays pending without repeating Delete or losing the saved image', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, failPaths: ['/cleanup'], responses: {result: {state: 'complete'}}});
  Object.assign(h.storage, {active, config});
  const {message, sender} = pairedImageResult();

  const response = await send(h, message, sender);

  assert.equal(response.ok, true);
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result', 'cleanup', 'cleanup']);
  assert.equal(h.requests[1].body.cleanup_status, 'confirmation_required');
  assert.equal(h.requests[2].body.cleanup_status, 'failed');
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-delete').length, 1);
  assert.equal(h.storage.lastJob.state, 'complete');
  assert.equal(h.storage.lastJob.cleanup_status, 'pending');
  assert.equal(h.storage.active, undefined);

  const duplicate = await send(h, message, sender);
  assert.ok(duplicate.error);
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-delete').length, 1);
});

test('polling heartbeats but does not claim or repeat cleanup while deletion cleanup is in flight', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, holdPath: '/cleanup', responses: {
    result: {state: 'complete'}, cleanup: [
      {state: 'complete', cleanup_status: 'confirmation_required'},
      {state: 'complete', cleanup_status: 'deleted'}
    ]
  }});
  Object.assign(h.storage, {active, config});
  const {message, sender} = pairedImageResult();
  let finishResult;
  const finished = new Promise(resolve => h.receive(message, sender, value => { finishResult = value; resolve(value); }));
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.requests.some(call => call.url.endsWith('/cleanup')));

  h.fireAlarm();
  for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result', 'cleanup', 'heartbeat']);
  assert.equal(h.requests.filter(call => call.url.endsWith('/next')).length, 0);
  assert.equal(h.requests.filter(call => call.url.endsWith('/cleanup')).length, 1);
  assert.equal(h.storage.active, active);

  h.releaseNetwork();
  await finished;
  assert.equal(finishResult.ok, true);
  assert.equal(h.storage.active, undefined);
});

test('poll heartbeats during owner confirmation without inspecting or claiming another job', async () => {
  const active = {jobId: 'job-1', tabId: 7};
  const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
  const h = harness({active, holdDeleteConfirmation: true, responses: {result: {state: 'complete'}, cleanup: [
    {state: 'complete', cleanup_status: 'confirmation_required'},
    {state: 'complete', cleanup_status: 'deleted'}
  ]}});
  Object.assign(h.storage, {active, config});
  const {message, sender} = pairedImageResult();
  let result;
  const finished = new Promise(resolve => h.receive(message, sender, value => { result = value; resolve(value); }));
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.requests[1].body.cleanup_status, 'confirmation_required');

  h.fireAlarm();
  for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['result', 'cleanup', 'heartbeat']);
  assert.equal(h.requests[2].body.tab_ready, false);
  assert.equal(h.requests[2].body.worker_version, manifest.version);
  assert.equal(h.requests[2].body.content_receiver, 'unreported');
  assert.equal(h.requests[2].body.receiver_error, '');
  assert.equal(h.requests.some(call => call.url.endsWith('/next')), false);
  assert.equal(h.tabMessages.filter(call => call.message.type === 'image-inspect').length, 0);

  h.releaseDeleteConfirmation();
  await finished;
  assert.equal(result.ok, true);
  assert.equal(h.storage.lastJob.cleanup_status, 'deleted');
});

test('collect-existing requires the paired current tab and a claimed job', async t => {
  await t.test('routes only an authenticated claimed job to the paired tab', async () => {
    const active = {jobId: 'job-1', tabId: 7, job: {
      job_id: 'job-1', prompt: 'draw a cat', expected_model: 'Create image'
    }};
    const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
    const h = harness({active, state: {state: 'claimed', expected_model: 'Create image'}});
    Object.assign(h.storage, {active, config});

    const response = await send(h, {type: 'collect-existing', tabId: 7});

    assert.equal(response.ok, true);
    assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['state']);
    assert.equal(h.requests[0].body.client_id, 'client');
    assert.equal(h.tabMessages.length, 1);
    assert.equal(h.tabMessages[0].id, 7);
    assert.equal(h.tabMessages[0].message.type, 'image-collect');
    assert.equal(h.tabMessages[0].message.job.job_id, 'job-1');
    assert.equal(h.tabMessages[0].message.job.expected_model, 'Create image');
    assert.equal(h.tabMessages[0].message.job.prompt, 'draw a cat');
  });

  await t.test('rejects a different current tab before status or content access', async () => {
    const active = {jobId: 'job-1', tabId: 7};
    const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
    const h = harness({active});
    Object.assign(h.storage, {active, config});

    const response = await send(h, {type: 'collect-existing', tabId: 8});

    assert.ok(response.error);
    assert.equal(h.requests.length, 0);
    assert.equal(h.tabMessages.length, 0);
  });

  await t.test('rejects terminal jobs without content access', async () => {
    const active = {jobId: 'job-1', tabId: 7};
    const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
    const h = harness({active, state: {state: 'complete', expected_model: 'Create image'}});
    Object.assign(h.storage, {active, config});

    const response = await send(h, {type: 'collect-existing', tabId: 7});

    assert.ok(response.error);
    assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['state']);
    assert.equal(h.tabMessages.length, 0);
  });

  await t.test('rejects image collection for a preflight job', async () => {
    const job = {...imageJob([referenceImage(1, 'reference')]), preflight_only: true, clear_preflight_uploads: true};
    const active = {jobId: job.job_id, tabId: 7, job: metadataOnly(job)};
    const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
    const h = harness({active, state: {state: 'claimed', expected_model: 'Create image'}});
    Object.assign(h.storage, {active, config});

    const response = await send(h, {type: 'collect-existing', tabId: 7});

    assert.match(response.error, /Preflight never generates an image to collect/);
    assert.equal(h.requests.length, 0);
    assert.equal(h.tabMessages.length, 0);
  });

  for (const [name, invalidJob] of [
    ['legacy active record without original job', undefined],
    ['mismatched persisted job id', {job_id: 'other-job', prompt: 'draw a cat', expected_model: 'Create image'}],
    ['missing original prompt', {job_id: 'job-1', prompt: 12, expected_model: 'Create image'}],
    ['model differs from authenticated status', {job_id: 'job-1', prompt: 'draw a cat', expected_model: 'GPT-6 Thinking'}]
  ]) await t.test(`rejects ${name} without content access`, async () => {
    const active = {jobId: 'job-1', tabId: 7, ...(invalidJob ? {job: invalidJob} : {})};
    const config = {token: 'secret', clientId: 'client', tabId: 7, account: 'second'};
    const h = harness({active, state: {state: 'claimed', expected_model: 'Create image'}});
    Object.assign(h.storage, {active, config});

    const response = await send(h, {type: 'collect-existing', tabId: 7});

    assert.ok(response.error);
    assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['state']);
    assert.equal(h.tabMessages.length, 0);
  });
});
