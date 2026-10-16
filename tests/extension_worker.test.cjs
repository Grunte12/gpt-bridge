const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../extensions/chatgpt-image/worker.js'), 'utf8');

function harness({tabUrl = 'https://chatgpt.com/', tabUrlRedacted = false, tabExists = true, active = null, state = {state: 'claimed', expected_model: 'Create image'}, next = {}, inspection = {fresh: true, model: 'Create image'}, preparation = {fresh: true, model: 'Create image'}, inspectError = '', prepareError = '', deleteResponse = {deleted: true}, deleteError = '', holdDeleteConfirmation = false, autoDeleteConfirmation = false, responses = {}, failPaths = [], storage: sharedStorage = null, failures = 0, httpError = 0, holdPath = '', holdTabLookup = false} = {}) {
  let listener;
  let alarmListener;
  const storage = sharedStorage || {};
  if (active) storage.active = active;
  const requests = [];
  const alarms = [];
  const tabLookups = [];
  const tabMessages = [];
  let releaseNetwork;
  const networkGate = new Promise(resolve => { releaseNetwork = resolve; });
  let releaseTabLookup;
  const tabGate = new Promise(resolve => { releaseTabLookup = resolve; });
  let releaseDeleteConfirmation;
  const deleteGate = new Promise(resolve => { releaseDeleteConfirmation = resolve; });
  const chrome = {
    storage: {local: {
      async get(keys) { const out = {}; for (const key of Array.isArray(keys) ? keys : [keys]) out[key] = storage[key]; return out; },
      async set(values) { Object.assign(storage, values); },
      async remove(keys) { for (const key of Array.isArray(keys) ? keys : [keys]) delete storage[key]; }
    }},
    runtime: {onMessage: {addListener(fn) { listener = fn; }}},
    alarms: {onAlarm: {addListener(fn) { alarmListener = fn; }}, async create(...args) { alarms.push(args); }, async clear(...args) { alarms.push(['clear', ...args]); }},
    tabs: {
      async get(id) { tabLookups.push(id); if (holdTabLookup) await tabGate; return tabExists ? {id, ...(tabUrlRedacted ? {} : {url: tabUrl})} : null; },
      async sendMessage(id, message) {
        tabMessages.push({id, message});
        if (message.type === 'image-inspect') {
          if (inspectError) throw new Error(inspectError);
          return inspection;
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
    }
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
  return {storage, requests, alarms, tabLookups, tabMessages, receive: listener,
    fireAlarm() { alarmListener({name: 'poll'}); },
    releaseNetwork() { releaseNetwork(); },
    releaseTabLookup() { releaseTabLookup(); },
    releaseDeleteConfirmation() { releaseDeleteConfirmation(); }};
}

const pairedImageResult = (overrides = {}) => ({
  message: {type: 'image-result', jobId: 'job-1', imageBase64: 'cG5n', chatPath: '/c/123e4567-e89b-12d3-a456-426614174000', ...overrides},
  sender: {tab: {id: 7}, url: 'https://chatgpt.com/c/123e4567-e89b-12d3-a456-426614174000'}
});

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
  assert.deepEqual(h.requests[0].body, {client_id: 'client-id', account: 'second', visible_model: 'Create image'});
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
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-job'), false);
    assert.equal(h.tabMessages.some(call => call.message.type === 'image-prepare'), false);
    assert.equal(h.storage.config, config);
    assert.equal(h.storage.connection.state, 'needs_tab');
  });
});

test('a URL-redacted paired tab is checked through its content script before claiming', async () => {
  const config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'second'};
  const job = {job_id: 'job-1', prompt: 'draw once', expected_model: 'Create image'};
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
  const job = {job_id: 'job-1', prompt: 'draw once', expected_model: 'Create image'};
  const h = harness({inspection: {fresh: false, model: ''}, next: job});
  Object.assign(h.storage, {config});

  h.fireAlarm();
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));

  assert.deepEqual(h.requests.map(call => call.url.split('/').at(-1)), ['heartbeat', 'next', 'heartbeat']);
  assert.equal(h.requests[0].body.tab_ready, false);
  assert.equal(h.requests[1].body.client_id, 'saved-client');
  assert.equal(h.requests[2].body.tab_ready, true);
  assert.deepEqual(h.tabMessages.map(call => call.message.type), ['image-inspect', 'image-prepare', 'image-job']);
  assert.equal(JSON.stringify(h.tabMessages[1].message), JSON.stringify({type: 'image-prepare', job}));
  assert.equal(JSON.stringify(h.tabMessages[2].message), JSON.stringify({type: 'image-job', job}));
  assert.equal(h.storage.active.jobId, 'job-1');
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
