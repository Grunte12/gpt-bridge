// Operates only the ordinary visible composer and its newly generated image.
// UI changes fail closed; never call private ChatGPT APIs or solve verification.
(() => {
  let running = false;
  let cleanupTarget = null;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const visible = el => !!el && el.getClientRects().length > 0;
  const normalizedText = text => text.replace(/\s+/g, " ").trim();
  const imageChipSelector = '[data-inline-selection-pill][data-system-hint-type="picture_v2"], [data-prompt-link-href="chatgpt-system-hint://picture_v2"]';
  const imageChip = editor => editor?.querySelector(imageChipSelector);
  const promptText = element => {
    const text = element.value ?? element.innerText;
    const chip = imageChip(element);
    return normalizedText(chip ? text.replace(chip.innerText, " ") : text);
  };
  const busy = () => visible(document.querySelector('[data-testid="stop-button"], button[aria-label="Stop"]'));
  const assistants = () => [...document.querySelectorAll('[data-message-author-role="assistant"]')];
  const conversation = () => document.querySelector('[role="region"][aria-label="Conversation"]');
  const turnHeadings = text => [...(conversation()?.querySelectorAll("h4") || [])].filter(el => el.textContent.trim() === text);
  const verificationRequired = () => [...document.querySelectorAll(
    'iframe[src*="challenges.cloudflare.com"], #challenge-running, #challenge-stage'
  )].some(visible);
  const editorElement = () => [...document.querySelectorAll('#prompt-textarea[contenteditable="true"], textarea#prompt-textarea, [role="textbox"][contenteditable="true"][aria-label="Ask ChatGPT"]')].find(visible);
  const hasTurns = () => assistants().length || document.querySelector('[data-message-author-role="user"]') ||
    turnHeadings("You said:").length || turnHeadings("ChatGPT said:").length;
  function idleEditor() {
    if (location.origin !== "https://chatgpt.com") throw new Error("Wrong site");
    if (verificationRequired()) throw new Error("Owner action required: complete verification in ChatGPT. Nothing was submitted.");
    if (new URL(location.href).searchParams.get("temporary-chat") === "true")
      throw new Error("Use a normal ChatGPT chat, not temporary chat. Nothing was submitted.");
    const editor = editorElement();
    if (!visible(editor)) throw new Error("ChatGPT composer unavailable. Nothing was submitted.");
    if (busy() || promptText(editor)) throw new Error("Preserve the draft or running work. Nothing was submitted.");
    if (document.querySelector('input[type="file"]')?.files?.length ||
        document.querySelector('[data-testid="file-upload-progress"], [data-testid="attachment-preview"], [data-testid="file-thumbnail"]'))
      throw new Error("Remove existing attachments before using the image worker");
    return editor;
  }
  async function waitFor(find, detail) {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      if (verificationRequired()) throw new Error("Owner action required: complete verification in ChatGPT. Nothing was submitted.");
      const result = find();
      if (result) return result;
      await sleep(100);
    }
    throw new Error(detail + ". Nothing was submitted.");
  }
  async function prepare(job) {
    if (job?.expected_model !== "Create image") throw new Error("Native image mode is Create image");
    // React may briefly unmount the composer just after an image completes.
    // Wait for that UI, without navigating or clearing an unseen draft.
    await waitFor(() => visible(editorElement()) && editorElement(), "ChatGPT composer unavailable");
    let editor = idleEditor();
    if (hasTurns()) {
      const newChat = [...document.querySelectorAll('button[aria-label="New chat"]')].find(visible) ||
        [...document.querySelectorAll("button")].find(el => visible(el) && normalizedText(el.textContent) === "New chat");
      if (!newChat) throw new Error("Native New chat control unavailable. Nothing was submitted.");
      newChat.click();
      await waitFor(() => !hasTurns() && visible(editorElement()) && editorElement(), "Fresh chat did not become ready");
      editor = idleEditor();
    }
    if (!visible(imageChip(editor))) {
      const tools = [...document.querySelectorAll('button[aria-label="Add files and more"]')].find(visible);
      if (!tools) throw new Error("Native image tools unavailable. Nothing was submitted.");
      tools.click();
      const create = await waitFor(() => [...document.querySelectorAll("button")].find(el =>
        visible(el) && /^Create image(?:\b|Visualize)/.test(normalizedText(el.textContent))), "Native Create image control unavailable");
      idleEditor();
      create.click();
      await waitFor(() => visible(imageChip(editorElement())), "Native Create image selection did not appear");
    }
    inspect(job);
    return {fresh: true, model: "Create image"};
  }
  function inspect(job) {
    if (location.origin !== "https://chatgpt.com") throw new Error("Wrong site");
    if (verificationRequired()) throw new Error("Owner action required: complete verification in ChatGPT. Nothing was submitted.");
    const editor = editorElement();
    if (!visible(editor) || !visible(imageChip(editor)))
      throw new Error("Select native Create image in a normal fresh chat first. Plain chat and temporary chat are not image mode.");
    if (job.expected_model !== "Create image")
      throw new Error("Visible model label does not match expected_model. Native image mode is Create image.");
    if (busy() || assistants().length || document.querySelector('[data-message-author-role="user"]') ||
        turnHeadings("You said:").length || turnHeadings("ChatGPT said:").length || promptText(editor))
      throw new Error("Use a fresh empty chat with no draft or running work. Nothing was submitted.");
    if (document.querySelector('input[type="file"]')?.files?.length ||
        document.querySelector('[data-testid="file-upload-progress"], [data-testid="attachment-preview"], [data-testid="file-thumbnail"]'))
      throw new Error("Remove existing attachments before using the image worker");
    return editor;
  }
  async function deleteSavedChat(message) {
    const target = cleanupTarget;
    if (!target || message.jobId !== target.jobId || message.chatPath !== target.path ||
        location.origin !== "https://chatgpt.com" || location.pathname !== target.path ||
        !/^\/c\/[a-f0-9-]{36}$/.test(target.path))
      throw new Error("Only this worker's saved image chat can be deleted");
    idleEditor();
    const users = turnHeadings("You said:");
    if (users.length !== 1 || turnHeadings("ChatGPT said:").length !== 1 ||
        !users[0].nextElementSibling || promptText(users[0].nextElementSibling) !== normalizedText(target.prompt))
      throw new Error("Chat changed after generation; nothing was deleted");
    const more = [...document.querySelectorAll('button[aria-label="More"]')].find(visible);
    if (!more) throw new Error("Native chat menu unavailable; saved image is safe");
    // This native menu trigger opens on pointerdown, not programmatic click.
    more.dispatchEvent(new PointerEvent("pointerdown", {bubbles: true, button: 0, pointerType: "mouse", isPrimary: true}));
    const remove = await waitFor(() => [...document.querySelectorAll('[role="menuitem"]')].find(el =>
      visible(el) && normalizedText(el.textContent) === "Delete"), "Native Delete control unavailable");
    idleEditor();
    if (location.pathname !== target.path) throw new Error("Chat changed; nothing was deleted");
    cleanupTarget = null; // Open confirmation once, only after the local file receipt.
    remove.click();
    const dialog = await waitFor(() => [...document.querySelectorAll('[role="dialog"]')].find(el =>
      visible(el) && [...el.querySelectorAll("button")].some(button => normalizedText(button.textContent) === "Delete chat")),
      "Native deletion confirmation unavailable");
    const notified = await chrome.runtime.sendMessage({type: "image-delete-prompt", jobId: message.jobId});
    if (notified?.ok !== true) throw new Error("Saved image is safe; deletion confirmation could not be recorded");
    // No final click without a trusted user click or one job-scoped MCP approval.
    const finalDelete = [...dialog.querySelectorAll("button")].find(button => normalizedText(button.textContent) === "Delete chat");
    let confirmed = false;
    const confirmation = event => { if (event.isTrusted) confirmed = true; };
    finalDelete.addEventListener("click", confirmation, {capture: true});
    try {
      const deadline = Date.now() + 15 * 60 * 1000;
      let checkedConfirmation = 0;
      while (Date.now() < deadline) {
        await sleep(250);
        if (location.pathname !== target.path) {
          if (confirmed) return {deleted: true};
          throw new Error("Chat changed without deletion confirmation; inspect it before further cleanup");
        }
        if (!confirmed && !visible(dialog)) throw new Error("Deletion was not confirmed; inspect this chat before any further cleanup");
        if (!confirmed && Date.now() - checkedConfirmation >= 2500) {
          checkedConfirmation = Date.now();
          const approval = await chrome.runtime.sendMessage({type: "image-delete-confirmation", jobId: message.jobId});
          if (approval?.error) throw new Error("Deletion approval unavailable; inspect this chat, do not repeat automatically");
          if (approval?.confirmed === true) {
            if (location.pathname !== target.path || !visible(dialog) || !visible(finalDelete) || finalDelete.disabled)
              throw new Error("Approved deletion dialog changed; nothing was clicked");
            idleEditor();
            confirmed = true;
            finalDelete.click();
          }
        }
      }
      throw new Error("Deletion confirmation timed out; saved image is safe, do not repeat automatically");
    } finally { finalDelete.removeEventListener("click", confirmation, {capture: true}); }
  }
  async function run(job, collectOnly = false) {
    let submitted = collectOnly;
    try {
      const prompt = "Create one image. Return a generated image, not just a description.\n\n" + job.prompt;
      if (collectOnly) {
        if (location.origin !== "https://chatgpt.com" || job.expected_model !== "Create image")
          throw new Error("Wrong site or model; existing image was not collected");
        if (verificationRequired() || busy() || turnHeadings("You said:").length !== 1 || turnHeadings("ChatGPT said:").length !== 1)
          throw new Error("Inspect the completed single-turn conversation before collecting; nothing was submitted");
        const userBody = turnHeadings("You said:")[0].nextElementSibling;
        if (!userBody || typeof job.prompt !== "string" || promptText(userBody) !== normalizedText(prompt))
          throw new Error("Existing conversation does not match this job's prompt; image was not collected");
      } else {
        const editor = inspect(job);
        editor.focus();
        if (editor instanceof HTMLTextAreaElement) {
          Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(editor, prompt);
          editor.dispatchEvent(new Event("input", {bubbles: true}));
        } else {
          // insertText enters text through the contenteditable editor, not its HTML.
          if (!document.execCommand("insertText", false, prompt)) throw new Error("Editor rejected text insertion");
          editor.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: prompt}));
        }
        await sleep(400);
        if (!visible(imageChip(editor)) || promptText(editor) !== normalizedText(prompt)) throw new Error("Composer text or Create image selection did not match; not submitted");
        if (verificationRequired()) throw new Error("Owner action required: complete verification in ChatGPT. Nothing was submitted.");
        const send = document.querySelector('[data-testid="send-button"], button[aria-label="Send"]');
        if (!visible(send) || send.disabled) throw new Error("Native send button unavailable; not submitted");
        submitted = true;  // From here an uncertain result MUST NOT be retried.
        send.click();
      }
      const deadline = Date.now() + 15 * 60 * 1000;
      let previous = "", stable = 0;
      while (Date.now() < deadline) {
        await sleep(2500);
        if (verificationRequired()) throw new Error("Owner action required: complete verification and inspect ChatGPT before any new request.");
        const message = assistants().at(-1) || (turnHeadings("ChatGPT said:").length === 1 ? conversation() : null);
        const images = message ? [...message.querySelectorAll("img")].filter(img =>
          visible(img) && img.complete && img.naturalWidth >= 512 && img.naturalHeight >= 512) : [];
        if (images.length > 1) throw new Error("Multiple images returned; inspect ChatGPT instead of choosing silently");
        const img = images[0];
        if (!img || busy()) { stable = 0; continue; }
        const source = img.currentSrc || img.src;
        stable = source === previous ? stable + 1 : 0;
        previous = source;
        if (stable < 2) continue;
        // Read only the asset already displayed by ChatGPT, never auth or API data.
        const url = new URL(source, location.href);
        if (!["https:", "blob:"].includes(url.protocol)) throw new Error("Unsupported displayed image source");
        const response = await fetch(url.href, {signal: AbortSignal.timeout(30000)});
        if (!response.ok) throw new Error("Displayed image could not be read; use its native download manually");
        const blob = await response.blob();
        if (!/^image\/(png|jpeg|webp)(;|$)/i.test(blob.type) || blob.size > 25 * 1024 * 1024)
          throw new Error("Generated asset is not a supported image under 25 MiB");
        const imageBase64 = await new Promise((resolve, reject) => {
          const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(",")[1]);
          reader.onerror = reject; reader.readAsDataURL(blob);
        });
        cleanupTarget = {jobId: job.job_id, path: location.pathname, prompt};
        const result = await chrome.runtime.sendMessage({type: "image-result", jobId: job.job_id, imageBase64,
          chatPath: location.pathname});
        if (result?.error) throw new Error("Image result could not be saved. Inspect ChatGPT; do not regenerate.");
        return;
      }
      throw new Error("Timed out; generation may still complete. Inspect ChatGPT before resubmitting.");
    } catch (error) {
      await chrome.runtime.sendMessage({type: "image-result", jobId: job.job_id,
        error: (submitted ? "Submission attempted. " : "Not submitted. ") + error.message}).catch(() => {});
    } finally { running = false; }
  }
  chrome.runtime.onMessage.addListener((message, _sender, reply) => {
    if (message.type === "image-delete") {
      void deleteSavedChat(message).then(reply, error => reply({error: error.message}));
      return true;
    }
    if (message.type === "image-prepare") {
      if (running) { reply({error: "Content worker already running"}); return; }
      running = true;
      void prepare(message.job).then(reply, error => reply({error: error.message})).finally(() => { running = false; });
      return true;
    }
    if (message.type === "image-inspect") {
      try {
        if (running) throw new Error("Content worker already running");
        const model = "Create image";
        inspect({expected_model: model});
        reply({fresh: true, model});
      } catch (error) { reply({error: error.message}); }
      return;
    }
    if (!["image-job", "image-collect"].includes(message.type)) return;
    if (running) { reply({error: "Content worker already running"}); return; }
    running = true;
    reply({accepted: true});
    void run(message.job, message.type === "image-collect");
  });
})();
