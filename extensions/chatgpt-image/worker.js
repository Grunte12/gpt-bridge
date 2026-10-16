// No cookies, webRequest, debugger, CDP, screenshots or ChatGPT backend calls.
const endpoint = "http://127.0.0.1:18767";
let polling = false;
let managing = false;
let finishing = false;
async function request(config, path, data) {
  const response = await fetch(endpoint + path, {method: "POST", cache: "no-store",
    headers: {"Authorization": "Bearer " + config.token, "Content-Type": "application/json"},
    body: JSON.stringify(data), signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw Object.assign(new Error("Local bridge request failed: " + response.status), {status: response.status});
  return response.json();
}
async function connection(state, detail) {
  await chrome.storage.local.set({connection: {state, detail, checkedAt: Date.now()}});
}
async function publicStatus() {
  const {config, connection: status, active, lastJob} = await chrome.storage.local.get(["config", "connection", "active", "lastJob"]);
  return {configured: !!config, account: config?.account, tabId: config?.tabId,
    connection: status || {state: config ? "checking" : "unpaired"},
    active: active ? {jobId: active.jobId} : null, lastJob: lastJob || null};
}
async function poll() {
  if (polling || managing) return;
  polling = true;
  try {
    const {config, active} = await chrome.storage.local.get(["config", "active"]);
    if (!config) return;
    if (config.account !== "second" || !Number.isInteger(config.tabId) || typeof config.token !== "string" ||
        typeof config.clientId !== "string") {
      await connection("needs_pairing", "การจับคู่เดิมไม่ถูกต้อง กรุณาเชื่อมบัญชี second ใหม่");
      return;
    }
    if (finishing) {
      await request(config, "/heartbeat", {client_id: config.clientId, account: config.account,
        visible_model: "Create image", tab_ready: false});
      return;
    }
    let ready = {fresh: false}, available = false;
    try {
      const tab = await chrome.tabs.get(config.tabId);
      // activeTab grants may expire after extension reload. A successful message
      // to our ChatGPT-only content script still verifies the paired receiver;
      // do not mistake a redacted tab URL for a closed tab or ask for tabs access.
      if (!tab.url || new URL(tab.url).origin === "https://chatgpt.com") {
        ready = await chrome.tabs.sendMessage(config.tabId, {type: "image-inspect"}) || ready;
        available = true;
      }
    } catch (_) { /* A missing tab never changes the account or creates another tab. */ }
    await request(config, "/heartbeat", {client_id: config.clientId, account: config.account,
      visible_model: "Create image", tab_ready: ready.fresh === true && ready.model === "Create image"});
    if (active) {
      const state = await request(config, "/state", {client_id: config.clientId, job_id: active.jobId});
      if (finishing) return;
      if (!["complete", "failed", "interrupted"].includes(state.state)) {
        await connection("busy", "กำลังรับภาพจากงานเดิม ไม่ส่งคำขอซ้ำ");
        return;
      }
      await chrome.storage.local.set({lastJob: state});
      await chrome.storage.local.remove("active");
      if (state.state === "interrupted") {
        await connection("interrupted", "MCP รีสตาร์ตระหว่างทำงาน ตรวจภาพเดิมก่อน ไม่มีการส่งซ้ำ");
        return;
      }
    }
    if (!available) {
      await connection("needs_tab", "เปิดแท็บ ChatGPT ที่เชื่อมไว้ หรือเชื่อมแท็บ second ใหม่ในตัวเลือก");
      return;
    }
    await connection("ready", "พร้อมรับคำสั่งภาพใหม่ ส่วนขยายจะเตรียมแชตและเลือก Create image ให้เอง");
    // Claims are durable and at-most-once. An extension restart never replays a job.
    const job = await request(config, "/next", {client_id: config.clientId});
    if (!job.job_id) return;
    await chrome.storage.local.set({active: {jobId: job.job_id, tabId: config.tabId, job}});
    await connection("busy", "กำลังสร้างภาพ ไม่ต้องพิมพ์ในแท็บที่เชื่อมไว้");
    try {
      if (ready.fresh !== true || ready.model !== "Create image") {
        const prepared = await chrome.tabs.sendMessage(config.tabId, {type: "image-prepare", job});
        if (prepared?.fresh !== true || prepared.model !== "Create image")
          throw new Error(prepared?.error || "Native image chat could not be prepared");
        await request(config, "/heartbeat", {client_id: config.clientId, account: config.account,
          visible_model: "Create image", tab_ready: true});
      }
      const accepted = await chrome.tabs.sendMessage(config.tabId, {type: "image-job", job});
      if (!accepted?.accepted) throw new Error("Content worker did not accept this job");
    } catch (error) {
      const result = await request(config, "/result", {client_id: config.clientId, job_id: job.job_id,
        error: "Not submitted or delivery uncertain. " + error.message + ". No automatic resubmission; inspect ChatGPT first."});
      await chrome.storage.local.set({lastJob: result});
      await chrome.storage.local.remove("active");
      await connection("failed", "แท็บไม่รับงาน ตรวจ ChatGPT ก่อนสั่งใหม่ ไม่มีการส่งซ้ำ");
    }
  } catch (error) {
    await connection(error.status === 401 ? "needs_pairing" : "offline", error.status === 401
      ? "รหัสในเครื่องเปลี่ยน ต้องจับคู่ใหม่หนึ่งครั้ง"
      : "รอ MCP กลับมา ส่วนขยายจะเชื่อมให้อัตโนมัติ ไม่ต้องกรอกรหัสซ้ำ");
  } finally { polling = false; }
}
async function resume() {
  const {config} = await chrome.storage.local.get("config");
  if (!config) return;
  await chrome.alarms.create("poll", {periodInMinutes: 0.5});
  await poll();
}
chrome.runtime.onStartup?.addListener(() => void resume());
chrome.runtime.onInstalled?.addListener(() => void resume());
void resume();
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === "poll") void poll(); });
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  void (async () => {
    const manage = !sender.tab && ["pair", "disconnect"].includes(message.type);
    if (manage && (polling || managing)) throw new Error("กำลังตรวจการเชื่อมต่อ รอสักครู่แล้วลองอีกครั้ง");
    if (manage) managing = true;
    let resumePolling = false;
    try {
    if (message.type === "get-status" && !sender.tab) {
      if (message.refresh !== false) await poll();
      return publicStatus();
    }
    if (message.type === "pair" && !sender.tab) {
      if (message.account !== "second" || message.confirmedAccount !== true)
        throw new Error("โหมดทดลองใช้เฉพาะบัญชี second กรุณายืนยันบัญชีก่อนเชื่อม");
      if (!Number.isInteger(message.tabId))
        throw new Error("เปิดแท็บ ChatGPT ที่ต้องการใช้งานก่อน");
      const tab = await chrome.tabs.get(message.tabId);
      if (new URL(tab.url || "about:blank").origin !== "https://chatgpt.com")
        throw new Error("เปิดแท็บ ChatGPT ที่ต้องการใช้งานก่อน");
      const {active, config: saved} = await chrome.storage.local.get(["active", "config"]);
      const token = message.token?.trim() || (saved?.account === "second" ? saved.token : "");
      if (typeof token !== "string" || token.length < 32) throw new Error("รหัสจับคู่ไม่ถูกต้อง");
      if (active) throw new Error("มีงานค้างอยู่ ตรวจ MCP และ ChatGPT ก่อนเชื่อมใหม่");
      const ready = await chrome.tabs.sendMessage(message.tabId, {type: "image-inspect"});
      if (!ready?.fresh || typeof ready.model !== "string" || !ready.model.trim() || ready.model.length > 100)
        throw new Error(ready?.error || "ยังตรวจแชตว่างและโมเดลไม่ได้ รีเฟรชแท็บ ChatGPT แล้วเชื่อมใหม่");
      const config = {token, tabId: message.tabId,
        clientId: saved?.account === "second" && typeof saved.clientId === "string" ? saved.clientId : crypto.randomUUID(), account: "second"};
      await request(config, "/pair", {client_id: config.clientId, account: config.account, visible_model: ready.model});
      await chrome.storage.local.set({config});
      resumePolling = true;
      await connection("ready", "รอคำสั่งสร้างภาพจากเอเจนต์ได้เลย");
      await chrome.alarms.create("poll", {periodInMinutes: 0.5});
      return {ok: true};
    }
    if (message.type === "disconnect" && !sender.tab) {
      const {config, active} = await chrome.storage.local.get(["config", "active"]);
      if (active) {
        if (!config) throw new Error("ตรวจ ChatGPT และสถานะ MCP ก่อนล้างงานค้าง");
        const state = await request(config, "/state", {client_id: config.clientId, job_id: active.jobId});
        if (!["complete", "failed", "interrupted"].includes(state.state))
          throw new Error("งานยังไม่จบ ตรวจ ChatGPT และสถานะ MCP ก่อน รักษาการเชื่อมต่อไว้เพื่อรับผล");
      }
      await chrome.storage.local.remove(["config", "active", "connection", "lastJob"]);
      await chrome.alarms.clear("poll");
      return {ok: true};
    }
    if (message.type === "collect-existing" && !sender.tab) {
      const {config, active} = await chrome.storage.local.get(["config", "active"]);
      if (!config || !active || message.tabId !== config.tabId || active.tabId !== config.tabId)
        throw new Error("เปิดแท็บเดิมที่กำลังรับงานก่อน รับภาพได้เท่านั้น ไม่ส่งงานใหม่");
      const state = await request(config, "/state", {client_id: config.clientId, job_id: active.jobId});
      if (state.state !== "claimed") throw new Error("งานนี้ไม่ได้อยู่ในสถานะรอรับภาพ");
      if (active.job?.job_id !== active.jobId || typeof active.job.prompt !== "string" ||
          active.job.expected_model !== state.expected_model)
        throw new Error("รุ่นเดิมไม่ได้เก็บข้อมูลยืนยันงาน ห้ามรับภาพอัตโนมัติ กรุณาตรวจผลใน ChatGPT");
      const result = await chrome.tabs.sendMessage(config.tabId, {type: "image-collect",
        job: active.job});
      if (!result?.accepted) throw new Error(result?.error || "ยังรับภาพจากแท็บเดิมไม่ได้");
      return {ok: true};
    }
    if (["image-delete-prompt", "image-delete-confirmation"].includes(message.type)) {
      const {config, active} = await chrome.storage.local.get(["config", "active"]);
      if (!finishing || !config || !active || sender.tab?.id !== config.tabId || sender.tab.id !== active.tabId ||
          new URL(sender.url).origin !== "https://chatgpt.com" || message.jobId !== active.jobId)
        throw new Error("Deletion confirmation is not from the paired saved-image job");
      if (message.type === "image-delete-confirmation")
        return request(config, "/cleanup-confirmation", {client_id: config.clientId, job_id: active.jobId});
      const state = await request(config, "/cleanup", {client_id: config.clientId, job_id: active.jobId,
        cleanup_status: "confirmation_required"});
      await chrome.storage.local.set({lastJob: state});
      await connection("confirmation_required", state.cleanup_confirmation === "requested"
        ? "บันทึกและตรวจไฟล์แล้ว กำลังลบแชตของงานนี้ตามนโยบายอัตโนมัติ"
        : "บันทึกไฟล์ภาพแล้ว ให้เอเจนต์ขอยืนยันจากคุณก่อนลบแชทผ่าน MCP");
      return {ok: true};
    }
    if (message.type === "image-result") {
      const {config, active} = await chrome.storage.local.get(["config", "active"]);
      if (!config || !active || sender.tab?.id !== config.tabId || sender.tab.id !== active.tabId ||
          new URL(sender.url).origin !== "https://chatgpt.com" || message.jobId !== active.jobId)
        throw new Error("Result is not from the paired job/tab");
      // ChatGPT changes chats through SPA navigation; sender.url can retain the
      // previous document path. The paired content receiver verifies the live
      // path and original prompt again before it opens Delete confirmation.
      const cleanup = !message.error && /^\/c\/[a-f0-9-]{36}$/.test(message.chatPath || "");
      finishing = true;
      let result;
      try {
        result = await request(config, "/result", {client_id: config.clientId, job_id: active.jobId,
          ...(message.error ? {error: message.error} : {image_base64: message.imageBase64, cleanup_pending: cleanup,
            ...(cleanup ? {chat_path: message.chatPath} : {})})});
        if (cleanup && result.state === "complete") {
          let removed;
          try {
            removed = await chrome.tabs.sendMessage(config.tabId,
              {type: "image-delete", jobId: active.jobId, chatPath: message.chatPath});
          } catch (_) { removed = {error: "Deletion delivery uncertain; inspect this chat, do not repeat automatically"}; }
          try {
            result = await request(config, "/cleanup", {client_id: config.clientId, job_id: active.jobId,
              cleanup_status: removed?.deleted === true ? "deleted" : "failed",
              error: removed?.error || (removed?.deleted === true ? "" : "Deletion was not confirmed")});
          } catch (_) {
            result = {...result, cleanup_status: "pending", cleanup_error: "Saved image is safe; cleanup receipt unavailable. Do not regenerate or delete again automatically."};
          }
        }
        await chrome.storage.local.set({lastJob: result});
        await chrome.storage.local.remove("active");
        await connection(message.error ? "failed" : "complete", message.error
          ? "งานไม่สำเร็จ ตรวจ ChatGPT ก่อนสั่งใหม่ ไม่มีการลองซ้ำอัตโนมัติ"
          : cleanup && result.cleanup_status !== "deleted"
            ? "รับไฟล์ภาพแล้ว แต่ยังยืนยันการลบไม่ได้ ตรวจแชตเดิม ไม่ต้องเจนซ้ำ"
            : cleanup ? "รับไฟล์ภาพและลบแชตแล้ว พร้อมรับภาพถัดไป"
              : "รับไฟล์ภาพแล้ว สั่งภาพถัดไปผ่าน MCP ได้เลย ส่วนขยายเตรียมแชตให้เอง");
        return {ok: true};
      } finally { finishing = false; }
    }
    throw new Error("Unknown extension message");
    } finally {
      if (manage) {
        managing = false;
        if (resumePolling) void poll();
      }
    }
  })().then(reply, error => reply({error: error.message}));
  return true;
});
