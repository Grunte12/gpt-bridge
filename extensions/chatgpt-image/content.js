// Operates only the ordinary visible composer and its newly generated image.
// UI changes fail closed; never call private ChatGPT APIs or solve verification.
(() => {
  let running = false;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const visible = el => !!el && el.getClientRects().length > 0;
  const normalizedText = text => text.replace(/\s+/g, " ").trim();
  const imageChipSelector = '[data-inline-selection-pill][data-system-hint-type="picture_v2"]';
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
  function inspect(job) {
    if (location.origin !== "https://chatgpt.com") throw new Error("Wrong site");
    if (verificationRequired()) throw new Error("Owner action required: complete verification in ChatGPT. Nothing was submitted.");
    const editor = document.querySelector('#prompt-textarea[contenteditable="true"], textarea#prompt-textarea, [role="textbox"][contenteditable="true"][aria-label="Ask ChatGPT"]');
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
        const result = await chrome.runtime.sendMessage({type: "image-result", jobId: job.job_id, imageBase64});
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
