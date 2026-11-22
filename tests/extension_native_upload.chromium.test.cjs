// Real offline DOM and File/DataTransfer/image decoding; ChatGPT/runtime remain fixtures.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const source = fs.readFileSync(path.join(__dirname, '../extensions/chatgpt-image/content.js'), 'utf8');
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aE1sAAAAASUVORK5CYII=';
const bytes = Buffer.from(png, 'base64');
test('native upload readiness: real Chromium success and fail-closed missing/pending/reordered cards', async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  try {
    const context = await browser.newContext({serviceWorkers: 'block'});
    let network = 0;
    await context.route('**/*', route => {
      if (route.request().isNavigationRequest()) return route.fulfill({contentType:'text/html', body:'<form><div id="prompt-textarea" contenteditable="true"><span data-inline-selection-pill data-system-hint-type="picture_v2">Create image</span></div><input type="file" accept="image/png" multiple><button type="button" data-testid="send-button">Send</button></form><style>#prompt-textarea{min-height:40px}img{width:20px;height:20px}span{display:inline-block}</style>'});
      network++; return route.abort();
    });
    const page = await context.newPage();
    for (const mode of ['ready', 'missing', 'pending', 'reordered']) {
      await page.goto('https://chatgpt.com/');
      await page.evaluate(({mode, png}) => {
        window.events = []; window.clicks = 0; window.listener = null;
        window.chrome = {runtime:{onMessage:{hasListener:fn=>window.listener===fn, addListener:fn=>window.listener=fn},sendMessage:async message=>{window.events.push(message);return {ok:true};}}};
        document.addEventListener('click', () => window.clicks++);
        document.querySelector('input').addEventListener('change', event => {
          const files = [...event.target.files];
          if (mode === 'reordered') files.reverse();
          for (const file of files) {
            const card = document.createElement('div');
            card.dataset.testid = 'attachment-preview';
            const image = document.createElement('img'); image.alt = file.name;
            if (mode !== 'missing') image.src = 'data:image/png;base64,' + png;
            const remove = document.createElement('button'); remove.type='button'; remove.setAttribute('aria-label', 'Remove ' + file.name); remove.textContent='Remove';
            card.append(image, remove); document.querySelector('form').append(card);
          }
          if (mode === 'pending') {const progress=document.createElement('span');progress.setAttribute('role','progressbar');document.querySelector('form').append(progress);}
          // Keep the 15 s production deadline; accelerate only the fixture's clock.
          if (mode !== 'ready') {const now=Date.now;let ticks=0;Date.now=()=>now()+ticks++*1000;}
        });
      }, {mode,png});
      await page.addScriptTag({content:source});
      const images = [1,2].map(order=>({order,name:`input-00${order}.png`,role:'reference',description:'fixture',mime:'image/png',bytes:bytes.length,data_base64:png,sha256:crypto.createHash('sha256').update(bytes).digest('hex')}));
      await page.evaluate(job=>window.listener({type:'image-job',job},{},()=>{}),{job_id:'fixture',prompt:'fixture',expected_model:'Create image',mode:'create',images,preflight_only:true,clear_preflight_uploads:false});
      await page.waitForFunction(()=>window.events.some(event=>event.type==='image-result'));
      const result = await page.evaluate(()=>({events:window.events,clicks:window.clicks}));
      const receipt = result.events.find(event=>event.type==='image-result');
      assert.equal(result.clicks,0,mode+' must never click Send');
      if (mode === 'ready') assert.equal(receipt.preflightReady,true,JSON.stringify(receipt));
      else {
        assert.match(receipt.error,/Not submitted\. Native uploads not verified ready;/);
        assert.match(receipt.error,/Upload readiness: /);
        assert.ok(!receipt.error.includes('input-001'), 'diagnostics omit filenames');
        if (mode === 'pending') assert.match(receipt.error,/"pending":true/);
      }
    }
    assert.equal(network,0);
    console.log(JSON.stringify({browser:browser.version(),scenarios:4,liveNetworkRequests:network}));
  } finally {await browser.close();}
});
