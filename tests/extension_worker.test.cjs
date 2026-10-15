const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../extensions/chatgpt-image/worker.js'), 'utf8');

function harness({tabUrl = 'https://chatgpt.com/', tabExists = true, active = null, state = {state: 'claimed', expected_model: 'Create image'}, next = {}, inspection = {fresh: true, model: 'Create image'}, storage: sharedStorage = null, failures = 0, httpError = 0, holdPath = '', holdTabLookup = false} = {}) {
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
  const chrome = {
    storage: {local: {
      async get(keys) { const out = {}; for (const key of Array.isArray(keys) ? keys : [keys]) out[key] = storage[key]; return out; },
      async set(values) { Object.assign(storage, values); },
      async remove(keys) { for (const key of Array.isArray(keys) ? keys : [keys]) delete storage[key]; }
    }},
    runtime: {onMessage: {addListener(fn) { listener = fn; }}},
    alarms: {onAlarm: {addListener(fn) { alarmListener = fn; }}, async create(...args) { alarms.push(args); }, async clear(...args) { alarms.push(['clear', ...args]); }},
    tabs: {
      async get(id) { tabLookups.push(id); if (holdTabLookup) await tabGate; return tabExists ? {id, url: tabUrl} : null; },
      async sendMessage(id, message) { tabMessages.push({id, message}); return message.type === 'image-inspect' ? inspection : {accepted: true}; }
    }
  };
  const context = {chrome, URL, crypto: {randomUUID: () => 'client-id'}, AbortSignal,
    async fetch(url, options) {
      const body = JSON.parse(options.body);
      requests.push({url, body, authorization: options.headers.Authorization});
      if (holdPath && url.endsWith(holdPath)) await networkGate;
      if (failures > 0) { failures--; throw new Error('offline'); }
      if (httpError) return {ok: false, status: httpError, json: async () => ({})};
      const response = url.endsWith('/state') ? state : url.endsWith('/next') ? next : {};
      return {ok: true, json: async () => response};
    }};
  vm.runInNewContext(source, context, {filename: 'worker.js'});
  return {storage, requests, alarms, tabLookups, tabMessages, receive: listener,
    fireAlarm() { alarmListener({name: 'poll'}); },
    releaseNetwork() { releaseNetwork(); },
    releaseTabLookup() { releaseTabLookup(); }};
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

test('missing or wrong-domain paired tab heartbeats not-ready and never polls jobs', async t => {
  for (const [name, options] of [
    ['missing tab', {tabExists: false}],
    ['wrong domain', {tabUrl: 'https://example.com/'}],
    ['native image chip missing', {inspection: {error: 'Create image unavailable'}}]
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
    assert.equal(h.storage.config, config);
    assert.equal(h.storage.connection.state, 'needs_tab');
  });
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
