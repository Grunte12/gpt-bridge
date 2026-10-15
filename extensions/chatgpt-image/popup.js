const $ = selector => document.querySelector(selector);
const labels = {
  checking: "กำลังตรวจการเชื่อมต่อ", unpaired: "เชื่อมครั้งแรก",
  ready: "พร้อมรับงาน", busy: "กำลังสร้างภาพ", complete: "รับภาพเรียบร้อย",
  needs_tab: "เชื่อมแล้ว เตรียมแท็บอีกนิด", offline: "รอ MCP กลับมา",
  needs_pairing: "ต้องเชื่อมใหม่", interrupted: "ตรวจงานเดิมก่อน", failed: "งานไม่สำเร็จ"
};
let current = {configured: false, connection: {state: "checking"}};
let relinking = false;
let busy = false;
function notice(text = "") {
  $("#notice").textContent = text;
  $("#notice").hidden = !text;
}
function render(status) {
  current = status;
  const state = status.connection?.state || "unpaired";
  document.body.dataset.state = state;
  $("#connection-title").textContent = labels[state] || labels.checking;
  $("#connection-detail").textContent = status.connection?.detail || "เชื่อมแท็บเพียงครั้งเดียว ครั้งต่อไปไม่ต้องกรอกรหัสซ้ำ";
  $("#identity").hidden = !status.configured;
  $("#pair-form").hidden = status.configured && !relinking && state !== "needs_pairing";
  $("#token-row").hidden = status.configured && state !== "needs_pairing";
  $("#token").required = !$("#token-row").hidden;
  $("#pair-hint").textContent = status.configured && state !== "needs_pairing"
    ? "ใช้รหัสที่จำไว้แล้ว ยืนยันบัญชีของแท็บนี้ก่อนเปลี่ยนแท็บ"
    : "รหัสนี้ไม่ใช่รหัสผ่านหรือโทเคน ChatGPT บัญชีที่ใช้ต้องตรวจด้วยตัวคุณเอง";
  $("#refresh").hidden = !status.configured;
  $("#advanced").hidden = !status.configured;
  $("#collect").hidden = !status.active;
  $("#disconnect").disabled = !!status.active || busy;
  const job = status.lastJob;
  $("#last-job").hidden = !job;
  $("#last-job").textContent = !job ? "" : job.state === "complete"
    ? "ภาพล่าสุดบันทึกแล้ว" + (job.dimensions ? ` · ${job.dimensions.join(" × ")} พิกเซล` : "")
    : job.state === "interrupted" ? "งานก่อนหน้าถูกขัดจังหวะ ไม่มีการส่งซ้ำ" : "งานก่อนหน้าไม่สำเร็จ ไม่มีการลองซ้ำอัตโนมัติ";
}
async function refresh(check = true) {
  const status = await chrome.runtime.sendMessage({type: "get-status", refresh: check});
  if (status?.error) throw new Error(status.error);
  if (status) render(status);
}
async function action(run) {
  if (busy) return;
  busy = true;
  notice();
  for (const button of document.querySelectorAll("button")) button.disabled = true;
  try { await run(); } catch (error) { notice(error.message || "ยังติดต่อส่วนขยายไม่ได้ ลองเปิดหน้าต่างนี้ใหม่"); }
  finally {
    busy = false;
    for (const button of document.querySelectorAll("button")) button.disabled = false;
    render(current);
  }
}
$("#pair-form").onsubmit = event => {
  event.preventDefault();
  void action(async () => {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const result = await chrome.runtime.sendMessage({type: "pair", tabId: tab?.id,
      account: "second", confirmedAccount: $("#confirm-account").checked, token: $("#token").value.trim()});
    $("#token").value = "";
    if (result?.error) throw new Error(result.error);
    relinking = false;
    $("#confirm-account").checked = false;
    await refresh();
  });
};
$("#refresh").onclick = () => void action(() => refresh());
$("#relink").onclick = () => {
  relinking = true;
  render(current);
  $("#confirm-account").focus();
};
for (const [selector, type] of [["#disconnect", "disconnect"], ["#collect", "collect-existing"]]) {
  $(selector).onclick = () => void action(async () => {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const result = await chrome.runtime.sendMessage({type, tabId: tab?.id});
    if (result?.error) throw new Error(result.error);
    if (type === "disconnect") relinking = false;
    await refresh();
  });
}
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && ["config", "connection", "active", "lastJob"].some(key => key in changes))
    void refresh(false).catch(() => {});
});
void refresh().catch(() => notice("ยังติดต่อส่วนขยายไม่ได้ ลองปิดแล้วเปิดหน้าต่างนี้ใหม่"));
