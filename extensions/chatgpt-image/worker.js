// No cookies, webRequest, debugger, CDP, screenshots or ChatGPT backend calls.
const endpoint = "http://127.0.0.1:18767";
const workerVersion = chrome.runtime.getManifest().version;
let polling = false;
let managing = false;
let finishing = false;
let receiverRecoveryTab = null;
let soonTimer = null;
let recoveryTabId = null;
const maxInputBytes = 8 * 1024 * 1024; // Bridge messaging budget, not a provider count limit.
function isManagementSender(sender) {
  if (!sender?.tab) return true;
  try {
    const url = new URL(sender.url || ""), extension = new URL(chrome.runtime.getURL(""));
    return url.protocol === extension.protocol && url.host === extension.host;
  }
  catch (_) { return false; }
}
const imageMetadata = image => Object.fromEntries(
  ["order", "role", "description", "name", "mime", "bytes", "sha256", "dimensions"].map(key => [key, image[key]]));
const jobMetadata = job => ({job_id: job.job_id, prompt: job.prompt, expected_model: job.expected_model,
  mode: job.mode || "create", ...(job.preflight_only === true ? {preflight_only: true} : {}),
  ...(job.preserve_chat === true ? {preserve_chat: true} : {}),
  ...(Number.isInteger(job.generation_timeout_seconds) ? {generation_timeout_seconds: job.generation_timeout_seconds} : {}),
  ...(typeof job.generation_baseline_seconds === "number" ? {generation_baseline_seconds: job.generation_baseline_seconds} : {}),
  ...(Number.isInteger(job.generation_timing_samples) ? {generation_timing_samples: job.generation_timing_samples} : {}),
  ...(Number.isInteger(job.retry_count) ? {retry_count: job.retry_count} : {}),
  ...(typeof job.replaces_job_id === "string" ? {replaces_job_id: job.replaces_job_id} : {}),
  ...(job.clear_preflight_uploads === true ? {clear_preflight_uploads: true} : {}),
  ...(job.preflight_cleanup_only === true ? {preflight_cleanup_only: true} : {}),
  ...(job.preflight_cleanup_resumed === true ? {preflight_cleanup_resumed: true} : {}),
  ...(job.collect_only === true ? {collect_only: true, preserve_chat: true, recovery_chat_path: job.recovery_chat_path} : {}),
  ...(job.output_binding_revision !== undefined ? {output_binding_revision: job.output_binding_revision} : {}),
  ...(job.images?.length ? {images: job.images.map(imageMetadata)} : {})});
function validateImages(job) {
  const mode = job.mode || "create", images = job.images || [];
  if (!["create", "edit"].includes(mode) || !Array.isArray(images)) throw new Error("Invalid image mode or inputs");
  if (job.collect_only !== undefined && (job.collect_only !== true || job.preserve_chat !== true || job.preflight_only ||
      !/^\/c\/[a-f0-9-]{36}$/.test(job.recovery_chat_path || "")))
    throw new Error("Output recovery must preserve the existing chat without preflight or submission");
  if (job.output_binding_revision !== undefined && (job.collect_only !== true || job.output_binding_revision !== 2))
    throw new Error("Unsupported output prompt binding revision");
  if (job.preflight_only !== undefined && typeof job.preflight_only !== "boolean") throw new Error("Invalid preflight flag");
  if (job.clear_preflight_uploads !== undefined && (typeof job.clear_preflight_uploads !== "boolean" ||
      (job.clear_preflight_uploads && !job.preflight_only))) throw new Error("Invalid preflight upload clearing flag");
  if (job.preflight_cleanup_only !== undefined && (typeof job.preflight_cleanup_only !== "boolean" ||
      (job.preflight_cleanup_only && (!job.preflight_only || !job.clear_preflight_uploads || !images.length))))
    throw new Error("Invalid cleanup-only preflight");
  if (job.preflight_cleanup_resumed !== undefined && (typeof job.preflight_cleanup_resumed !== "boolean" ||
      (job.preflight_cleanup_resumed && !job.preflight_cleanup_only)))
    throw new Error("Invalid inspected cleanup resume");
  let total = 0;
  for (const [index, image] of images.entries()) {
    if (!image || image.order !== index + 1 || !["source", "reference"].includes(image.role) ||
        typeof image.description !== "string" || !image.description.trim() || image.description.length > 200 ||
        !(job.preflight_cleanup_only ? /^input-\d{3,}(?:-[a-f0-9]{32})?(?:\([1-9]\d{0,5}\))?\.(png|jpg|webp)$/ :
          /^input-\d{3,}(?:-[a-f0-9]{32})?\.(png|jpg|webp)$/).test(image.name) ||
        !["image/png", "image/jpeg", "image/webp"].includes(image.mime) ||
        !Number.isInteger(image.bytes) || image.bytes <= 0 || image.bytes > maxInputBytes ||
        (job.preflight_cleanup_only || job.collect_only ? image.data_base64 !== undefined :
          typeof image.data_base64 !== "string" || image.data_base64.length !== 4 * Math.ceil(image.bytes / 3) ||
          !/^[A-Za-z0-9+/]*={0,2}$/.test(image.data_base64)) || !/^[a-f0-9]{64}$/.test(image.sha256))
      throw new Error("Invalid ordered local image payload");
    total += image.bytes;
    if (total > maxInputBytes) throw new Error("Inputs exceed the 8 MiB Bridge transport budget");
  }
  if (mode === "edit" && !images.some(image => image.role === "source")) throw new Error("Edit requires a source image");
  if (mode === "create" && images.some(image => image.role === "source")) throw new Error("Create accepts references, not edit sources");
}
const publicJob = job => job ? Object.fromEntries(Object.entries(job)
  .filter(([key]) => !["prompt", "client_id", "data_base64", "path"].includes(key))
  .map(([key, value]) => [key, key === "images" ? (Array.isArray(value) ? value.map(imageMetadata) : []) : value])) : null;
function pageHasFinishedOutput(ready) {
  const dom = ready?.result_dom;
  return !!dom && dom.busy === false && dom.assistant_body_found === true &&
    dom.user_headings === 1 && dom.assistant_headings === 1 &&
    Number.isInteger(dom.assistant_images) && dom.assistant_images >= 1 && dom.assistant_images <= 4 &&
    typeof dom.chat_path === "string" && /^\/c\/[a-f0-9-]{36}$/.test(dom.chat_path);
}
function scheduleSoon() {
  if (soonTimer) return;
  soonTimer = setTimeout(() => { soonTimer = null; void poll(); }, 3000);
  if (typeof soonTimer.unref === "function") soonTimer.unref();
}
function heartbeatFields(config, fields) {
  const recovery = ["none", "rebound", "unmatched"].includes(fields.tab_recovery) ? fields.tab_recovery : "none";
  const tabs = Number.isInteger(fields.chatgpt_tabs) && fields.chatgpt_tabs >= 0 ? Math.min(fields.chatgpt_tabs, 20) : 0;
  return {client_id: config.clientId, account: config.account, visible_model: "Create image", tab_id: config.tabId,
    worker_version: workerVersion, ...fields, tab_recovery: recovery, chatgpt_tabs: tabs};
}
async function findPairedTab(config) {
  // Match only the saved client marker. An open ChatGPT tab is not proof of the second account.
  if (!chrome.tabs.query || !/^[a-f0-9-]{36}$/.test(config.clientId || ""))
    return {count: 0, tabId: null, soleCandidateTabId: null};
  let tabs = [];
  try { tabs = await chrome.tabs.query({url: "https://chatgpt.com/*"}); }
  catch (_) { return {count: 0, tabId: null, soleCandidateTabId: null}; }
  if (!Array.isArray(tabs)) return {count: 0, tabId: null, soleCandidateTabId: null};
  const ids = [];
  for (const candidate of tabs) {
    if (!candidate || !Number.isInteger(candidate.id) || ids.length >= 20) continue;
    let originOk = !candidate.url;
    try { if (candidate.url) originOk = new URL(candidate.url).origin === "https://chatgpt.com"; } catch (_) { originOk = false; }
    if (originOk) ids.push(candidate.id);
  }
  const matches = [];
  for (const id of ids) {
    try {
      const reply = await chrome.tabs.sendMessage(id, {type: "image-identity"});
      if (reply?.client_id === config.clientId) matches.push(id);
    } catch (_) { /* No marker: leave the tab unpaired. */ }
  }
  return {count: ids.length, tabId: matches.length === 1 ? matches[0] : null,
    soleCandidateTabId: ids.length === 1 && matches.length === 0 ? ids[0] : null};
}
async function openRecoveryTab(config) {
  // One tab, only when this profile has none. Never chooses among existing accounts.
  if (!chrome.tabs?.create || !/^[a-f0-9-]{36}$/.test(config.clientId || "")) return null;
  if (recoveryTabId) {
    try { return await chrome.tabs.get(recoveryTabId); } catch (_) { recoveryTabId = null; }
  }
  const created = await chrome.tabs.create({url: "https://chatgpt.com/", active: false});
  if (!created || !Number.isInteger(created.id)) return null;
  recoveryTabId = created.id;
  const deadline = Date.now() + 12000;
  while (Date.now() < deadline) {
    let current;
    try { current = await chrome.tabs.get(created.id); } catch (_) { return null; }
    let originOk = false;
    try { originOk = new URL(current.url || "about:blank").origin === "https://chatgpt.com"; } catch (_) {}
    if (current.status === "complete" && originOk) {
      if (chrome.scripting?.executeScript) {
        try { await chrome.scripting.executeScript({target: {tabId: created.id}, files: ["content.js"]}); }
        catch (_) { /* The declared content script may already be attached. */ }
      }
      try {
        await chrome.tabs.sendMessage(created.id, {type: "image-bind", clientId: config.clientId});
      } catch (_) { /* Keep the tab. A later poll can attach the receiver. Do not open another. */ }
      return current;
    }
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  return null;
}
async function openTimeoutCleanupTab(job, preferredId) {
  const path = job?.chat_path;
  if (!chrome.tabs?.create || !/^\/c\/[a-f0-9-]{36}$/.test(path || ""))
    return {error: "The saved timeout chat path is invalid."};
  const expectedUrl = "https://chatgpt.com" + path;
  const matchesPath = tab => {
    try { const url = new URL(tab?.url || "about:blank"); return url.origin === "https://chatgpt.com" && url.pathname === path; }
    catch (_) { return false; }
  };
  let target = null;
  if (Number.isInteger(preferredId)) {
    try {
      const saved = await chrome.tabs.get(preferredId);
      if (matchesPath(saved)) target = saved;
    } catch (_) { /* A closed tab can be recreated from the server-saved path. */ }
  }
  if (!target && chrome.tabs.query) {
    try {
      const tabs = await chrome.tabs.query({url: expectedUrl});
      const exact = (Array.isArray(tabs) ? tabs : []).filter(matchesPath);
      if (exact.length === 1) target = exact[0];
      else if (exact.length > 1) return {error: "More than one tab matches the saved timeout chat."};
    } catch (_) { /* Create only the server-specified canonical chat below. */ }
  }
  if (!target) {
    try { target = await chrome.tabs.create({url: expectedUrl, active: false}); }
    catch (_) { return {error: "Could not open the saved timeout chat."}; }
  }
  if (!Number.isInteger(target?.id)) return {error: "Could not open the saved timeout chat."};
  const deadline = Date.now() + 12000;
  let injected = false;
  while (Date.now() < deadline) {
    let current;
    try { current = await chrome.tabs.get(target.id); }
    catch (_) { return {error: "The saved timeout chat tab closed before inspection."}; }
    let chatgptOrigin = false;
    try { chatgptOrigin = new URL(current.url || "about:blank").origin === "https://chatgpt.com"; } catch (_) {}
    if (!chatgptOrigin && current.status === "complete")
      return {error: "ChatGPT redirected away from the saved timeout chat."};
    if (chatgptOrigin && current.status === "complete") {
      if (!injected && chrome.scripting?.executeScript) {
        try { await chrome.scripting.executeScript({target: {tabId: target.id}, files: ["content.js"]}); }
        catch (_) { /* The declared content script may already be attached. */ }
        injected = true;
      }
      let inspected;
      try { inspected = await chrome.tabs.sendMessage(target.id, {type: "image-inspect"}); }
      catch (_) { await new Promise(resolve => setTimeout(resolve, 150)); continue; }
      if (typeof inspected?.error === "string" && inspected.error.startsWith("Owner action required"))
        return {error: "Owner action required: complete ChatGPT verification before timeout cleanup."};
      if (matchesPath(current) && inspected?.result_dom?.chat_path === path) return {tab: current};
    }
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  return {error: "The saved timeout chat did not reach its exact inspected path."};
}
async function request(config, path, data) {
  // chrome-extension:// is a loopback origin; labeling 127.0.0.1 as "local" breaks split LNA permissions.
  const response = await fetch(endpoint + path, {method: "POST", cache: "no-store",
    headers: {"Authorization": "Bearer " + config.token, "Content-Type": "application/json"},
    body: JSON.stringify(data), signal: AbortSignal.timeout(15000)});
  if (!response.ok) {
    let detail = "Local bridge request failed: " + response.status;
    if (path === "/pair" && response.status === 400) {
      try {
        if ((await response.json()).error === "finish the current job before pairing again; call wait and do not send again")
          detail = "A current image job or chat cleanup is still open. Call wait; do not send again. (HTTP 400)";
      } catch (_) {}
    }
    throw Object.assign(new Error(detail), {status: response.status});
  }
  return response.json();
}
function requestFailure(error) {
  if (Number.isInteger(error?.status)) return `HTTP ${error.status}`;
  const name = String(error?.name || "");
  return ["TypeError", "TimeoutError", "AbortError", "NetworkError", "SyntaxError"].includes(name) ? name : "Error";
}
async function connection(state, detail) {
  await chrome.storage.local.set({connection: {state, detail, checkedAt: Date.now()}});
}
async function publicStatus() {
  const {config, connection: status, active, lastJob} = await chrome.storage.local.get(["config", "connection", "active", "lastJob"]);
  return {configured: !!config, account: config?.account, tabId: config?.tabId,
    connection: status || {state: config ? "checking" : "unpaired"},
    active: active ? {jobId: active.jobId} : null, lastJob: publicJob(lastJob)};
}
function uploadDomDiagnostic(value) {
  const counts = ["file_inputs", "form_file_inputs", "image_inputs", "form_image_inputs",
    "multiple_image_inputs", "unrestricted_inputs", "attachment_cards"];
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).length !== counts.length + 1 || typeof value.editor_form !== "boolean" ||
      counts.some(key => !Number.isInteger(value[key]) || value[key] < 0 || value[key] > 10000)) return null;
  return {editor_form: value.editor_form, ...Object.fromEntries(counts.map(key => [key, value[key]]))};
}
function resultDomDiagnostic(value) {
  const counts = ["assistant_role_nodes", "user_headings", "assistant_headings", "assistant_images", "conversation_images"];
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length !== 8 ||
      typeof value.assistant_body_found !== "boolean" || typeof value.busy !== "boolean" ||
      typeof value.chat_path !== "string" || (value.chat_path !== "" && !/^\/c\/[a-f0-9-]{36}$/.test(value.chat_path)) ||
      counts.some(key => !Number.isInteger(value[key]) || value[key] < 0 || value[key] > 10000)) return null;
  return Object.fromEntries([...counts, "assistant_body_found", "busy", "chat_path"].map(key => [key, value[key]]));
}
function promptDomDiagnostic(value) {
  const counts = ["body_chars", "stripped_chars", "matched_chip_chars", "label_count"];
  const flags = ["starts_with_label", "ends_with_label"];
  const labelFlags = ["inline_pill", "system_hint", "prompt_link", "in_button", "matched_chip"];
  const tags = new Set(["DIV", "SPAN", "BUTTON", "A", "P", "OTHER"]);
  if (!value || Object.keys(value).length !== 7 ||
      counts.some(key => !Number.isInteger(value[key]) || value[key] < 0 || value[key] > (key === "label_count" ? 10000 : 100000)) ||
      flags.some(key => typeof value[key] !== "boolean") || !Array.isArray(value.labels) || value.labels.length > 8 ||
      value.labels.length !== Math.min(value.label_count, 8) || value.labels.some(label => !label ||
        Object.keys(label).length !== 7 || !tags.has(label.tag) || !tags.has(label.parent_tag) ||
        labelFlags.some(key => typeof label[key] !== "boolean"))) return null;
  return {...Object.fromEntries([...counts, ...flags].map(key => [key, value[key]])),
    labels: value.labels.map(label => Object.fromEntries(["tag", "parent_tag", ...labelFlags].map(key => [key, label[key]])))};
}
async function poll() {
  if (polling || managing) return;
  polling = true;
  try {
    const {config, active, lastJob} = await chrome.storage.local.get(["config", "active", "lastJob"]);
    if (!config) return;
    if (config.account !== "second" || !Number.isInteger(config.tabId) || typeof config.token !== "string" ||
        typeof config.clientId !== "string") {
      await connection("needs_pairing", "การจับคู่เดิมไม่ถูกต้อง กรุณาเชื่อมบัญชี second ใหม่");
      return;
    }
    const openCleanup = ["pending", "confirmation_required", "timeout_delete_pending", "timeout_delete_failed"]
      .includes(lastJob?.cleanup_status);
    const localJobOpen = !!active || (!!lastJob &&
      (!(["complete", "failed", "interrupted"].includes(lastJob.state)) || openCleanup));
    if (finishing) {
      await request(config, "/heartbeat", heartbeatFields(config, {tab_ready: false,
        content_receiver: "unreported", receiver_error: ""}));
      return;
    }
    let ready = {fresh: false}, available = false, tab;
    let contentReceiver = "tab_missing", receiverError = "tab_missing";
    let tabRecovery = "none", chatgptTabs = 0, soleSingleTabRecovery = false, staleWrongOrigin = false;
    try {
      tab = await chrome.tabs.get(config.tabId);
    } catch (_) { /* Never forward native exception text, which may include private URLs. */ }
    if (tab?.url) {
      try { if (new URL(tab.url).origin !== "https://chatgpt.com") { tab = null; staleWrongOrigin = true; } }
      catch (_) { tab = null; staleWrongOrigin = true; }
    }
    if (!tab) {
      const recovered = await findPairedTab(config);
      chatgptTabs = recovered.count;
      const candidateTabId = Number.isInteger(recovered.tabId) ? recovered.tabId : recovered.soleCandidateTabId;
      if (chatgptTabs === 1 && Number.isInteger(candidateTabId) && !localJobOpen) {
        const markerMatches = candidateTabId === recovered.tabId;
        const tabId = candidateTabId;
        let candidate;
        try { candidate = await chrome.tabs.get(tabId); } catch (_) { candidate = null; }
        let candidateIsChatgpt = !!candidate && !candidate.url;
        try { if (candidate?.url) candidateIsChatgpt = new URL(candidate.url).origin === "https://chatgpt.com"; } catch (_) {}
        if (candidateIsChatgpt) {
          const reboundConfig = {...config, tabId};
          await request(reboundConfig, "/heartbeat", heartbeatFields(reboundConfig, {tab_ready: false,
            content_receiver: "unreported", receiver_error: "", tab_recovery: "none", chatgpt_tabs: chatgptTabs}));
          if (!markerMatches) {
            try { await chrome.tabs.sendMessage(tabId, {type: "image-bind", clientId: config.clientId}); } catch (_) {}
          }
          config.tabId = tabId;
          await chrome.storage.local.set({config});
          tab = candidate;
          tabRecovery = "rebound";
          soleSingleTabRecovery = !markerMatches;
        } else tabRecovery = "unmatched";
      } else if (chatgptTabs === 0 && !localJobOpen) {
        const opened = await openRecoveryTab(config);
        if (opened && Number.isInteger(opened.id)) {
          config.tabId = opened.id;
          await chrome.storage.local.set({config});
          tab = opened;
          tabRecovery = "rebound";
          chatgptTabs = 1;
        }
      } else if (chatgptTabs > 0) tabRecovery = "unmatched";
    }
    if (!tab && staleWrongOrigin && chatgptTabs === 0) contentReceiver = receiverError = "wrong_origin";
    if (tab) {
      contentReceiver = "wrong_origin";
      receiverError = "wrong_origin";
      // activeTab grants may expire after extension reload. A successful message
      // to our ChatGPT-only content script still verifies the paired receiver;
      // do not mistake a redacted tab URL for a closed tab or ask for tabs access.
      let chatgptTab = !tab.url;
      try { if (tab.url) chatgptTab = new URL(tab.url).origin === "https://chatgpt.com"; } catch (_) {}
      if (chatgptTab) {
        for (let attempt = 0; attempt < 2; attempt++) {
          try {
            const inspected = await chrome.tabs.sendMessage(config.tabId, {type: "image-inspect",
              ...(/^[a-f0-9-]{36}$/.test(config.clientId) ? {clientId: config.clientId} : {})});
            const ownerBlocked = typeof inspected?.error === "string" && inspected.error.startsWith("Owner action required");
            if (ownerBlocked) {
              ready = inspected;
              contentReceiver = "available";
              receiverError = "";
            } else if (inspected && typeof inspected === "object" &&
                (typeof inspected.fresh === "boolean" || typeof inspected.error === "string")) {
              ready = inspected;
              available = true;
              contentReceiver = "available";
              receiverError = "";
              receiverRecoveryTab = null;
            } else {
              contentReceiver = "invalid_reply";
              receiverError = "invalid_reply";
            }
          } catch (error) {
            contentReceiver = "unavailable";
            const message = String(error?.message || "");
            receiverError = /receiving end does not exist|could not establish connection/i.test(message) ? "no_receiver"
              : /message port closed|message channel closed/i.test(message) ? "port_closed" : "message_failed";
            // Reattach only our bundled listener; never navigate or change a draft.
            if (attempt === 0 && receiverError === "no_receiver" &&
                receiverRecoveryTab !== config.tabId && chrome.scripting?.executeScript) {
              receiverRecoveryTab = config.tabId;
              try {
                await chrome.scripting.executeScript({target: {tabId: config.tabId}, files: ["content.js"]});
                continue;
              } catch (_) { /* Preserve the tab and expose no_receiver; no repeated recovery. */ }
            }
          }
          break;
        }
      }
    }
    if (soleSingleTabRecovery && available && (ready.fresh !== true || ready.model !== "Create image")) {
      try { ready = await chrome.tabs.sendMessage(config.tabId,
        {type: "image-prepare", job: {expected_model: "Create image"}}); }
      catch (_) { ready = {error: "Fresh composer preparation was unavailable"}; }
    }
    const beat = await request(config, "/heartbeat", heartbeatFields(config, {
      tab_ready: ready.fresh === true && ready.model === "Create image",
      input_protocol: [1, 2, 3, 4].includes(ready.input_protocol) ? ready.input_protocol : 0,
      tab_idle: typeof ready.idle === "boolean" ? ready.idle : null,
      tab_error: receiverError ? "Native tab inspection failed: " + receiverError : String(ready.error || "").slice(0, 300),
      content_receiver: contentReceiver, receiver_error: receiverError, tab_recovery: tabRecovery, chatgpt_tabs: chatgptTabs,
      upload_dom: uploadDomDiagnostic(ready.upload_dom), result_dom: resultDomDiagnostic(ready.result_dom),
      prompt_dom: promptDomDiagnostic(ready.prompt_dom)}));
    // The bridge asks an outdated worker to reload before timeout cleanup; no browser UI is needed.
    if (!active && beat?.next_action === "reload_extension" && chrome.runtime.reload) { chrome.runtime.reload(); return; }
    if (!active && lastJob?.cleanup_status === "timeout_delete_pending") {
      const cleanupJob = lastJob.timeout_cleanup_job;
      if (!cleanupJob || !/^[a-f0-9]{32}$/.test(cleanupJob.job_id || "") ||
          typeof cleanupJob.prompt !== "string" || !cleanupJob.prompt.trim() ||
          cleanupJob.expected_model !== "Create image" || cleanupJob.mode !== "create" ||
          !/^\/c\/[a-f0-9-]{36}$/.test(cleanupJob.chat_path || "")) {
        await connection("failed", "The previous timed-out image chat cannot be safely identified. Inspect MCP status; no new image was sent.");
        return;
      }
      const opened = await openTimeoutCleanupTab(cleanupJob, lastJob.timeout_cleanup_tab_id);
      const cleanupTab = opened?.tab;
      if (!cleanupTab) {
        const cleaned = await request(config, "/timeout-cleanup", {client_id: config.clientId, job_id: cleanupJob.job_id,
          deleted: false, error: opened?.error || "The exact saved timeout chat could not be inspected."});
        await chrome.storage.local.set({lastJob: cleaned});
        await connection("failed", "Exact timed-out chat cleanup needs owner review. No new image was sent.");
        return;
      }
      lastJob.timeout_cleanup_tab_id = cleanupTab.id;
      await chrome.storage.local.set({lastJob});
      let removed;
      try {
        removed = await chrome.tabs.sendMessage(cleanupTab.id, {type: "image-delete-timeout",
          job: cleanupJob, jobId: cleanupJob.job_id, chatPath: cleanupJob.chat_path});
      } catch (_) { removed = {error: "Timed-out chat cleanup handoff failed after extension reload"}; }
      const cleaned = await request(config, "/timeout-cleanup", {client_id: config.clientId, job_id: cleanupJob.job_id,
        deleted: removed?.deleted === true, error: removed?.error || ""});
      await chrome.storage.local.set({lastJob: cleaned});
      if (removed?.deleted === true && cleaned.cleanup_status === "deleted") {
        let cleanupTabCloseFailed = false;
        if (Number.isInteger(cleanupTab.id) && cleanupTab.id !== config.tabId) {
          try {
            if (!chrome.tabs.remove) throw new Error("Tab close unavailable");
            await chrome.tabs.remove(cleanupTab.id);
          } catch (_) { cleanupTabCloseFailed = true; }
        }
        let prepared;
        try { prepared = await chrome.tabs.sendMessage(config.tabId,
          {type: "image-prepare", job: {expected_model: "Create image"}}); }
        catch (_) { prepared = {error: "Fresh composer preparation was unavailable"}; }
        const ready = prepared?.fresh === true && prepared.model === "Create image";
        const detail = ready
          ? "Timed-out chat cleanup is complete; a fresh Create image composer is ready. No new image was sent."
          : "Timed-out chat cleanup is complete, but the selected fresh composer needs review. No new image was sent.";
        await connection(ready ? "ready" : "needs_tab", cleanupTabCloseFailed
          ? detail + " The separate cleanup tab could not be closed."
          : detail);
      } else {
        await connection("failed", "Exact timed-out chat cleanup needs owner review. No new image was sent.");
      }
      return;
    }
    if (active) {
      const state = await request(config, "/state", {client_id: config.clientId, job_id: active.jobId});
      if (finishing) return;
      if (!["complete", "failed", "interrupted"].includes(state.state)) {
        const alreadyRunning = typeof ready.error === "string" && ready.error.startsWith("Content worker already running");
        if (!alreadyRunning && available && pageHasFinishedOutput(ready) && active.visibleOutputSaved !== true &&
            active.job?.preflight_only !== true && active.job?.collect_only !== true) {
          active.visibleOutputSaved = true;
          await chrome.storage.local.set({active});
          try {
            const accepted = await chrome.tabs.sendMessage(config.tabId, {type: "image-collect",
              job: {...(active.job || {}), job_id: active.jobId, expected_model: "Create image", visible_output_only: true}});
            if (!accepted?.accepted) throw new Error(accepted?.error || "Content worker did not accept the finished image");
          } catch (_) {
            active.visibleOutputSaved = false;
            await chrome.storage.local.set({active});
          }
        }
        await connection("busy", "กำลังรับภาพจากงานเดิม ไม่ส่งคำขอซ้ำ");
        scheduleSoon();
        return;
      }
      if (state.cleanup_status === "timeout_delete_pending" && active.job?.job_id === active.jobId &&
          typeof active.job.prompt === "string" && /^\/c\/[a-f0-9-]{36}$/.test(state.chat_path || "")) {
        let removed;
        try {
          removed = await chrome.tabs.sendMessage(config.tabId, {type: "image-delete-timeout",
            job: active.job, jobId: active.jobId, chatPath: state.chat_path});
        } catch (_) { removed = {error: "Timed-out chat deletion delivery failed after restart"}; }
        state = await request(config, "/timeout-cleanup", {client_id: config.clientId, job_id: active.jobId,
          deleted: removed?.deleted === true, error: removed?.error || ""});
        if (removed?.deleted === true) scheduleSoon();
      }
      await chrome.storage.local.set({lastJob: state});
      await chrome.storage.local.remove("active");
      if (state.state === "interrupted") {
        await connection("interrupted", "MCP รีสตาร์ตระหว่างทำงาน ตรวจภาพเดิมก่อน ไม่มีการส่งซ้ำ");
        return;
      }
    }
    if (!available) {
      const ownerAction = typeof ready.error === "string" && ready.error.startsWith("Owner action required");
      await connection(tabRecovery === "unmatched" ? "needs_relink" : "needs_tab", ownerAction
        ? "ต้องยืนยันตัวตนในแท็บ ChatGPT ที่เปิดไว้ ไม่มีการส่งงาน"
        : receiverError === "no_receiver"
        ? "รีเฟรชแท็บ ChatGPT ที่เชื่อมไว้ครั้งเดียว ตัวรับจะกลับมาเอง ไม่ต้องกรอกรหัสใหม่"
        : tabRecovery === "unmatched"
        ? "มีแท็บ ChatGPT เปิดอยู่ แต่ยังไม่ใช่แท็บที่จับคู่ เปิดแท็บ second แล้วยืนยันด้านล่าง ใช้รหัสเดิม"
        : "ยังไม่มีแท็บ ChatGPT ส่วนขยายจะเปิดให้หนึ่งแท็บเมื่อไม่มีแท็บอื่น ถ้ามีหลายแท็บให้ยืนยันบัญชี second");
      return;
    }
    if (soleSingleTabRecovery) {
      const readyForImages = ready?.fresh === true && ready.model === "Create image";
      await connection(readyForImages ? "ready" : "needs_tab", readyForImages
        ? "Paired ChatGPT tab recovered after restart; Create image is ready. No image was sent."
        : String(ready?.error || "Recovered ChatGPT tab needs owner review; no image was sent."));
      return;
    }
    await connection("ready", "พร้อมรับคำสั่งภาพใหม่ ส่วนขยายจะเตรียมแชตและเลือก Create image ให้เอง");
    // Claims are durable and at-most-once. An extension restart never replays a job.
    const job = await request(config, "/next", {client_id: config.clientId});
    if (!job.job_id) return;
    try {
      validateImages(job);
      // Keep source bytes only in this one delivery, never extension storage/replay.
      const metadata = jobMetadata(job);
      await chrome.storage.local.set({active: {jobId: job.job_id, tabId: config.tabId, job: metadata}});
      await connection("busy", job.collect_only ? "กำลังรับภาพจากงานเดิมเท่านั้น ไม่ส่งซ้ำและไม่ลบแชต" : job.preflight_only
        ? "กำลังตรวจอัปโหลดเท่านั้น ไม่ส่งข้อความหรือสร้างภาพ"
        : "กำลังสร้างภาพ ไม่ต้องพิมพ์ในแท็บที่เชื่อมไว้");
      if (!job.preflight_cleanup_only && !job.collect_only && (ready.fresh !== true || ready.model !== "Create image")) {
        const prepared = await chrome.tabs.sendMessage(config.tabId, {type: "image-prepare", job: metadata});
        if (prepared?.fresh !== true || prepared.model !== "Create image")
          throw new Error(prepared?.error || "Native image chat could not be prepared");
        ready = prepared;
        await request(config, "/heartbeat", heartbeatFields(config, {tab_ready: true,
          input_protocol: [1, 2, 3, 4].includes(ready.input_protocol) ? ready.input_protocol : 0,
          tab_idle: typeof ready.idle === "boolean" ? ready.idle : null, tab_error: "",
          content_receiver: "available", receiver_error: "", tab_recovery: tabRecovery, chatgpt_tabs: chatgptTabs}));
      }
      if ((job.images?.length || job.mode === "edit") && ![1, 2, 3, 4].includes(ready.input_protocol))
        throw new Error("Refresh the paired ChatGPT tab to load local image input support; not submitted");
      if (job.preflight_only && ![2, 3, 4].includes(ready.input_protocol))
        throw new Error("Refresh the paired ChatGPT tab for no-Send preflight support; not submitted");
      if (job.clear_preflight_uploads && ![3, 4].includes(ready.input_protocol))
        throw new Error("Protocol 3 is required to clear verified preflight uploads; not submitted");
      if (job.preflight_cleanup_only && ready.input_protocol !== 4)
        throw new Error("Protocol 4 is required to clear an inspected failed preflight");
      const accepted = await chrome.tabs.sendMessage(config.tabId, {type: job.collect_only ? "image-collect" : "image-job", job});
      if (!accepted?.accepted) throw new Error("Content worker did not accept this job");
    } catch (error) {
      const result = await request(config, "/result", {client_id: config.clientId, job_id: job.job_id,
        error: (job.collect_only ? "Existing output recovery delivery failed or uncertain. " : "Not submitted or delivery uncertain. ") +
          error.message + ". No automatic resubmission; inspect ChatGPT first."});
      await chrome.storage.local.set({lastJob: result});
      await chrome.storage.local.remove("active");
      await connection("failed", "แท็บไม่รับงาน ตรวจ ChatGPT ก่อนสั่งใหม่ ไม่มีการส่งซ้ำ");
    }
  } catch (error) {
    await connection(error.status === 401 ? "needs_pairing" : "offline", error.status === 401
      ? "รหัสในเครื่องเปลี่ยน ต้องจับคู่ใหม่หนึ่งครั้ง"
      : `รอ MCP กลับมา ส่วนขยายจะเชื่อมให้อัตโนมัติ ไม่ต้องกรอกรหัสซ้ำ (${requestFailure(error)})`);
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
chrome.tabs.onReplaced?.addListener((addedTabId, removedTabId) => (async () => {
  const {config} = await chrome.storage.local.get("config");
  if (!config || config.tabId !== removedTabId || !Number.isInteger(addedTabId) || addedTabId === removedTabId) return;
  config.tabId = addedTabId;
  await chrome.storage.local.set({config});
})());
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  void (async () => {
    const managementSender = isManagementSender(sender);
    const manage = managementSender && ["pair", "disconnect"].includes(message.type);
    if (manage && (polling || managing)) throw new Error("กำลังตรวจการเชื่อมต่อ รอสักครู่แล้วลองอีกครั้ง");
    if (manage) managing = true;
    let resumePolling = false;
    try {
    if (message.type === "get-status" && managementSender) {
      if (message.refresh !== false) await poll();
      return publicStatus();
    }
    if (message.type === "pair" && managementSender) {
      if (message.account !== "second" || message.confirmedAccount !== true)
        throw new Error("โหมดทดลองใช้เฉพาะบัญชี second กรุณายืนยันบัญชีก่อนเชื่อม");
      if (message.retryTimeoutCleanup !== undefined && typeof message.retryTimeoutCleanup !== "boolean")
        throw new Error("Invalid timeout cleanup retry confirmation");
      if (!Number.isInteger(message.tabId))
        throw new Error("เปิดแท็บ ChatGPT ที่ต้องการใช้งานก่อน");
      const tab = await chrome.tabs.get(message.tabId);
      if (new URL(tab.url || "about:blank").origin !== "https://chatgpt.com")
        throw new Error("เปิดแท็บ ChatGPT ที่ต้องการใช้งานก่อน");
      const {active, config: saved} = await chrome.storage.local.get(["active", "config"]);
      const token = message.token?.trim() || (saved?.account === "second" ? saved.token : "");
      if (typeof token !== "string" || token.length < 32) throw new Error("รหัสจับคู่ไม่ถูกต้อง");
      if (active) throw new Error("มีงานค้างอยู่ ตรวจ MCP และ ChatGPT ก่อนเชื่อมใหม่");
      let inspected;
      try { inspected = await chrome.tabs.sendMessage(message.tabId, {type: "image-inspect"}); }
      catch (_) { throw new Error("ยังตรวจแท็บ ChatGPT ที่เลือกไม่ได้ รีเฟรชแท็บนั้นแล้วเชื่อมใหม่"); }
      if (!inspected || typeof inspected !== "object")
        throw new Error("ยังตรวจแท็บ ChatGPT ที่เลือกไม่ได้ รีเฟรชแท็บนั้นแล้วเชื่อมใหม่");
      const config = {token, tabId: message.tabId,
        clientId: saved?.account === "second" && typeof saved.clientId === "string" ? saved.clientId : crypto.randomUUID(), account: "second"};
      const pairPayload = {client_id: config.clientId, account: config.account,
        visible_model: typeof inspected.model === "string" && inspected.model.length <= 100 ? inspected.model : "Create image",
        input_protocol: [1, 2, 3, 4].includes(inspected.input_protocol) ? inspected.input_protocol : 0,
        tab_id: config.tabId};
      if (message.retryTimeoutCleanup === true) pairPayload.retry_timeout_cleanup = true;
      const paired = await request(config, "/pair", pairPayload);
      if (paired?.cleanup_pending === true) {
        const job = paired.timeout_cleanup_job;
        if (!job || !/^[a-f0-9]{32}$/.test(job.job_id || "") || typeof job.prompt !== "string" || !job.prompt.trim() ||
            job.expected_model !== "Create image" || job.mode !== "create" ||
            !/^\/c\/[a-f0-9-]{36}$/.test(job.chat_path || ""))
          throw new Error("A previous timed-out image chat cannot be safely identified. Inspect MCP status; no new image was sent.");
        const timeoutCleanupJob = {job_id: job.job_id, prompt: job.prompt, expected_model: job.expected_model,
          mode: job.mode, chat_path: job.chat_path};
        await chrome.storage.local.set({config, lastJob: {job_id: job.job_id, state: "failed",
          cleanup_status: "timeout_delete_pending", timeout_cleanup_job: timeoutCleanupJob}});
        try { await chrome.tabs.sendMessage(config.tabId, {type: "image-bind", clientId: config.clientId}); } catch (_) {}
        resumePolling = true;
        await connection("busy", "A previous timed-out chat needs exact cleanup. No new image will be sent.");
        await chrome.alarms.create("poll", {periodInMinutes: 0.5});
        return {ok: true};
      }
      await chrome.storage.local.set({config});
      try { await chrome.tabs.sendMessage(config.tabId, {type: "image-bind", clientId: config.clientId}); } catch (_) {}
      let prepared;
      try { prepared = await chrome.tabs.sendMessage(config.tabId,
        {type: "image-prepare", job: {expected_model: "Create image"}}); }
      catch (_) { prepared = {error: "Refresh the selected ChatGPT tab to load image preparation support"}; }
      resumePolling = true;
      await connection(prepared?.fresh === true && prepared.model === "Create image" ? "ready" : "needs_tab",
        prepared?.fresh === true && prepared.model === "Create image"
          ? "เตรียมแชตใหม่และเลือก Create image แล้ว รอคำสั่งสร้างภาพจากเอเจนต์ได้เลย"
          : String(prepared?.error || "เตรียมแชต Create image ไม่สำเร็จ รักษาดราฟต์และงานเดิมไว้ แล้วตรวจแท็บ ChatGPT"));
      await chrome.alarms.create("poll", {periodInMinutes: 0.5});
      return {ok: true};
    }
    if (message.type === "disconnect" && managementSender) {
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
    if (message.type === "collect-existing" && managementSender) {
      const {config, active} = await chrome.storage.local.get(["config", "active"]);
      if (!config || !active || message.tabId !== config.tabId || active.tabId !== config.tabId)
        throw new Error("เปิดแท็บเดิมที่กำลังรับงานก่อน รับภาพได้เท่านั้น ไม่ส่งงานใหม่");
      if (active.job?.preflight_only) throw new Error("Preflight never generates an image to collect");
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
    if (message.type === "image-timeout") {
      const {config, active} = await chrome.storage.local.get(["config", "active"]);
      if (!config || !active || sender.tab?.id !== config.tabId || sender.tab.id !== active.tabId ||
          new URL(sender.url).origin !== "https://chatgpt.com" || message.jobId !== active.jobId ||
          message.chatPath !== active.phaseChatPath || active.phase !== "remote_started")
        throw new Error("Adaptive timeout is not from the exact paired job/tab");
      let state = await request(config, "/timeout", {client_id: config.clientId, job_id: active.jobId,
        chat_path: message.chatPath});
      let removed;
      try {
        removed = await chrome.tabs.sendMessage(config.tabId, {type: "image-delete-timeout",
          job: active.job, jobId: active.jobId, chatPath: message.chatPath});
      } catch (_) { removed = {error: "Timed-out chat deletion delivery failed"}; }
      state = await request(config, "/timeout-cleanup", {client_id: config.clientId, job_id: active.jobId,
        deleted: removed?.deleted === true, error: removed?.error || ""});
      await chrome.storage.local.set({lastJob: state});
      await chrome.storage.local.remove("active");
      await connection(removed?.deleted === true ? "retrying" : "failed", removed?.deleted === true
        ? "งานเกินเวลา ลบแชตที่ค้างแล้ว กำลังเริ่มใหม่ในแชตใหม่หนึ่งครั้ง"
        : "งานเกินเวลาแต่ยังลบแชตเดิมไม่ได้ หยุดคิวเพื่อให้ตรวจสอบ");
      if (removed?.deleted === true) scheduleSoon();
      return {ok: removed?.deleted === true, state};
    }
    if (message.type === "image-phase") {
      const {config, active} = await chrome.storage.local.get(["config", "active"]);
      if (!config || !active || sender.tab?.id !== config.tabId || sender.tab.id !== active.tabId ||
          new URL(sender.url).origin !== "https://chatgpt.com" || message.jobId !== active.jobId)
        throw new Error("Lifecycle receipt is not from the exact paired job/tab");
      const result = await request(config, "/phase", {client_id: config.clientId, job_id: active.jobId,
        phase: message.phase, tab_id: config.tabId, ...(message.chatPath ? {chat_path: message.chatPath} : {})});
      active.phase = result.phase;
      if (message.chatPath) active.phaseChatPath = message.chatPath;
      await chrome.storage.local.set({active});
      return {ok: true, phase: result.phase};
    }
    if (message.type === "image-result") {
      const {config, active} = await chrome.storage.local.get(["config", "active"]);
      if (!config || !active || sender.tab?.id !== config.tabId || sender.tab.id !== active.tabId ||
          new URL(sender.url).origin !== "https://chatgpt.com" || message.jobId !== active.jobId)
        throw new Error("Result is not from the paired job/tab");
      if (!message.error && active.job?.preflight_only && (message.preflightReady !== true || message.imageBase64 || message.imagesBase64 || message.chatPath))
        throw new Error("Preflight cannot accept generated media or cleanup");
      if (message.preflightUploadsCleared !== undefined && typeof message.preflightUploadsCleared !== "boolean")
        throw new Error("Invalid preflight clearing receipt");
      if (message.preflightUploadsCleared === true && !active.job?.clear_preflight_uploads)
        throw new Error("Preflight upload clearing was not requested");
      if (!message.error && active.job?.clear_preflight_uploads && message.preflightUploadsCleared !== true)
        throw new Error("Verified preflight upload clearing receipt is required");
      if (message.preflightReady && !active.job?.preflight_only) throw new Error("Generation requires a saved image, not a readiness receipt");
      // ChatGPT changes chats through SPA navigation; sender.url can retain the
      // previous document path. The paired content receiver verifies the live
      // path and original prompt again before it opens Delete confirmation.
      const cleanup = !message.error && !active.job?.preserve_chat && !message.imagesBase64 && /^\/c\/[a-f0-9-]{36}$/.test(message.chatPath || "");
      finishing = true;
      let result;
      try {
        result = await request(config, "/result", {client_id: config.clientId, job_id: active.jobId,
          ...(message.error ? {error: message.error} : active.job?.preflight_only ? {preflight_ready: true,
            ...(message.preflightUploadsCleared === true ? {preflight_uploads_cleared: true} : {})} : {
              ...(message.imagesBase64 ? {images_base64: message.imagesBase64} : {image_base64: message.imageBase64}), cleanup_pending: cleanup,
              ...(/^\/c\/[a-f0-9-]{36}$/.test(message.chatPath || "") ? {chat_path: message.chatPath} : {})}),
          ...(message.promptBinding ? {prompt_binding: message.promptBinding} : {})});
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
        await connection(message.error ? "failed" : active.job?.preflight_only ? "preflight_complete" : "complete", message.error
          ? "งานไม่สำเร็จ ตรวจ ChatGPT ก่อนสั่งใหม่ ไม่มีการลองซ้ำอัตโนมัติ"
          : result.cleanup_status === "preserved" ? "บันทึกภาพที่ได้ครบแล้ว เก็บแชตเดิมไว้ ยังไม่ได้ลบแชต"
          : result.uploads_cleared ? "นำไฟล์แนบของงานที่หยุดก่อนส่งออกแล้ว แท็บว่าง ไม่ได้เจนภาพ"
          : active.job?.preflight_only ? result.preflight_uploads_cleared
            ? "ตรวจอัปโหลดผ่านและนำไฟล์แนบทดสอบออกแล้ว แท็บว่าง ไม่มีการส่งหรือเจนภาพ"
            : "ตรวจอัปโหลดพร้อมแล้ว ยังไม่ส่งและไม่เจนภาพ ดราฟต์ทดสอบยังอยู่ในแท็บเดิม"
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
