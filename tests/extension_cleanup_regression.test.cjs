const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');

const root = path.resolve(__dirname, '..');
// Reuse the existing browser double without registering or changing its suite.
const context = {require: name => name === 'node:test' ? () => {} : require(name),
  __dirname, Buffer, URL, AbortSignal, setTimeout, setImmediate};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'extension_worker.test.cjs'), 'utf8') +
  '\nglobalThis.helpers = {harness, send, pairedImageResult};', context);
const {harness, send, pairedImageResult} = context.helpers;

function durableClaim(mode, enabled) {
  return JSON.parse(execFileSync(path.join(root, '.venv/bin/python'), ['-c', `
import json, tempfile, sys
from pathlib import Path
from chatgpt_api.extension_bridge import ExtensionQueue
if '${mode}' == 'enqueue' and not hasattr(ExtensionQueue, 'enqueue'):
    print('null')
    sys.exit(0)
with tempfile.TemporaryDirectory() as directory:
    queue = ExtensionQueue(Path(directory), 'test', auto_delete_saved_chats=${enabled ? 'True' : 'False'})
    client = '123e4567-e89b-12d3-a456-426614174000'
    queue.pair(client, 'test', 'Create image', input_protocol=4, tab_id=7)
    receipt = queue.enqueue('cleanup-regression', 'One image.') if '${mode}' == 'enqueue' else queue.submit('One image.', 'Create image')
    claim = queue.claim(client)
    assert claim['job_id'] == receipt['job_id']
    assert queue.jobs[claim['job_id']]['state'] == 'claimed'
    assert json.loads((queue.root / claim['job_id'] / 'state.json').read_text())['state'] == 'claimed'
    print(json.dumps(claim))
`], {cwd: root, encoding: 'utf8'}));
}

for (const mode of ['submit', 'enqueue']) {
  for (const policy of ['automatic', 'disabled', 'preserve', 'nonboolean']) {
    test(`${mode} durable claim retains cleanup policy through polling: ${policy}`, async t => {
      const job = durableClaim(mode, policy !== 'disabled');
      if (job === null) return t.skip('enqueue is not present in this checkout');
      if (policy === 'preserve') job.preserve_chat = true;
      if (policy === 'nonboolean') job.auto_delete_saved_chat = 'true';
      const h = harness({next: job, responses: {result: {state: 'complete', cleanup_status:
        policy === 'automatic' ? 'pending' : 'preserved'}}});
      h.storage.config = {token: 'synthetic-token', clientId: 'saved-client', tabId: 7, account: 'test'};
      h.fireAlarm();
      for (let turn = 0; turn < 12; turn++) await new Promise(resolve => setImmediate(resolve));
      assert.equal(h.storage.active.jobId, job.job_id);
      assert.equal(h.storage.active.job.auto_delete_saved_chat === true,
        policy === 'automatic' || policy === 'preserve');
      assert.ok(h.tabMessages.some(call => call.message.type === 'image-job'));
      const {message, sender} = pairedImageResult({jobId: job.job_id});
      h.storage.active.phase = 'result_captured';
      h.storage.active.phaseChatPath = message.chatPath;
      assert.equal((await send(h, message, sender)).ok, true);
      const deletions = h.tabMessages.filter(call => call.message.type === 'image-delete');
      // Older receivers can open a manual confirmation when policy is off;
      // the metadata assertion above ensures they never inherit auto-consent.
      if (policy === 'preserve') assert.equal(deletions.length, 0);
      if (policy === 'automatic') {
        assert.equal(deletions.length, 1);
        assert.equal(deletions[0].message.jobId, job.job_id);
        assert.equal(deletions[0].message.chatPath, message.chatPath);
        assert.ok(h.requests.some(call => call.url.endsWith('/cleanup')));
      }
    });
  }
}

test('phase receipt retains bounded original error and no-retry warning', async () => {
  const source = fs.readFileSync(path.join(root, 'extensions/chatgpt-image/content.js'), 'utf8');
  const start = source.indexOf('  async function reportPhase(');
  const end = source.indexOf('\n  function ', start);
  assert.ok(start >= 0 && end > start);
  for (const error of ['Original durable failure', 'x'.repeat(300), 42]) {
    const phaseContext = {chrome: {runtime: {async sendMessage() { return {error}; }}}};
    vm.runInNewContext(source.slice(start, end) + '\nglobalThis.report = reportPhase;', phaseContext);
    await assert.rejects(phaseContext.report({job_id: 'job'}, 'prepared'), failure => {
      assert.equal(failure.message, 'Durable lifecycle receipt failed; inspect ChatGPT and do not retry: ' +
        String(error).slice(0, 240));
      return true;
    });
  }
});
