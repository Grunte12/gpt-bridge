// Operates only the ordinary visible composer and its newly generated image.
// UI changes fail closed; never call private ChatGPT APIs or solve verification.
(() => {
  const installed = globalThis.__gptBridgeImageWorkerListener;
  if (installed && chrome.runtime.onMessage.hasListener(installed)) return;
  let running = false;
  let cleanupTarget = null;
  let uploadBinding = null;
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
  const jobPrompt = job => {
    const images = job.images || [];
    const roles = images.map((image, index) => `Image ${index + 1}: ${image.role === "source" ? "SOURCE TO EDIT" : "REFERENCE GUIDANCE"} — ${image.description}`).join("\n");
    const intent = job.mode === "edit" ? "Edit the attached source image(s) following the instructions. Return one edited image." :
      "Create one image. Return a generated image, not just a description.";
    return intent + (roles ? "\nActual attachments, in upload order:\n" + roles : "") + "\n\n" + job.prompt;
  };
  const matchingDraft = (job, editor) => typeof job?.prompt === "string" &&
    visible(imageChip(editor)) && promptText(editor) === normalizedText(jobPrompt(job));
  const busy = () => visible(document.querySelector('[data-testid="stop-button"], button[aria-label="Stop"]'));
  const assistants = () => [...document.querySelectorAll('[data-message-author-role="assistant"]')];
  const conversation = () => document.querySelector('[role="region"][aria-label="Conversation"]');
  const turnHeadings = text => {
    const matches = root => [...(root?.querySelectorAll("h4") || [])].filter(el => visible(el) && el.textContent.trim() === text);
    // The labeled conversation region can stay mounted but hidden while the
    // visible "You said:" / "ChatGPT said:" turns render elsewhere.
    const scoped = matches(conversation());
    return scoped.length ? scoped : matches(document);
  };
  // Never fall back to the whole conversation: it also contains uploaded references.
  const assistantBody = () => assistants().at(-1) || turnHeadings("ChatGPT said:").at(-1)?.nextElementSibling || null;
  const displayedImages = root => root ? [...root.querySelectorAll("img")].filter(img =>
    visible(img) && img.complete && img.naturalWidth >= 512 && img.naturalHeight >= 512) : [];
  // The generated image can render in a gallery before the "ChatGPT said:" heading, outside its next sibling (seen live).
  // Fall back to gallery images after the last "You said:" heading: uploads are not in a gallery, earlier turns come before.
  function galleryImagesAfterUserHeading() {
    if (!turnHeadings("ChatGPT said:").length) return [];
    const user = turnHeadings("You said:").at(-1);
    return displayedImages(conversation()).filter(img => img.closest('[data-testid="generated-image-gallery"]') &&
      (!user || !!(user.compareDocumentPosition(img) & Node.DOCUMENT_POSITION_FOLLOWING)));
  }
  const outputImages = () => {
    const direct = displayedImages(assistantBody());
    return [...new Map((direct.length ? direct : galleryImagesAfterUserHeading()).map(img => [img.currentSrc || img.src, img])).values()];
  };
  function resultDomDiagnostics() {
    return {assistant_role_nodes: assistants().length, user_headings: turnHeadings("You said:").length,
      assistant_headings: turnHeadings("ChatGPT said:").length, assistant_body_found: !!assistantBody(),
      assistant_images: outputImages().length, conversation_images: displayedImages(conversation()).length,
      busy: busy(), chat_path: /^\/c\/[a-f0-9-]{36}$/.test(location.pathname) ? location.pathname : ""};
  }
  function originalPromptBinding(job) {
    const body = turnHeadings("You said:")[0]?.nextElementSibling;
    const expected = normalizedText(jobPrompt(job));
    const observed = body ? promptText(body) : "";
    const matches = element => {
      if (!element || !visible(element) || typeof element.innerText !== "string") return false;
      const rendered = normalizedText(element.innerText);
      if (rendered === expected) return true;
      const chips = [...element.querySelectorAll(imageChipSelector)].filter(visible);
      // Only the native leading image pill may be excluded, never wrapper text.
      return chips.length === 1 && normalizedText(chips[0].innerText) === "Create image" &&
        rendered.startsWith("Create image ") && rendered.slice("Create image ".length) === expected;
    };
    const count = body ? [...body.querySelectorAll("*")].filter(matches).length : 0;
    return {root_match: matches(body), exact_matching_descendant_count: count,
      expected_chars: expected.length, observed_chars: observed.length,
      ...(job.output_binding_revision === 2 ? {matcher_revision: 2} : {})};
  }
  function promptDomDiagnostics() {
    const body = turnHeadings("You said:")[0]?.nextElementSibling;
    const raw = normalizedText(body?.innerText || "");
    const chip = body && imageChip(body);
    const tags = new Set(["DIV", "SPAN", "BUTTON", "A", "P"]);
    const tag = element => tags.has(element?.tagName) ? element.tagName : "OTHER";
    const labels = body ? [...body.querySelectorAll("*")].filter(element => visible(element) &&
      typeof element.innerText === "string" && normalizedText(element.innerText) === "Create image") : [];
    return {body_chars: Math.min(raw.length, 100000), stripped_chars: Math.min(body ? promptText(body).length : 0, 100000),
      matched_chip_chars: Math.min(chip?.innerText?.length || 0, 100000), label_count: Math.min(labels.length, 10000),
      starts_with_label: raw.startsWith("Create image"), ends_with_label: raw.endsWith("Create image"),
      labels: labels.slice(0, 8).map(element => ({tag: tag(element), parent_tag: tag(element.parentElement),
        inline_pill: element.hasAttribute("data-inline-selection-pill"),
        system_hint: element.hasAttribute("data-system-hint-type"),
        prompt_link: element.hasAttribute("data-prompt-link-href"),
        in_button: !!element.closest("button"), matched_chip: element === chip}))};
  }
  const verificationRequired = () => [...document.querySelectorAll(
    'iframe[src*="challenges.cloudflare.com"], #challenge-running, #challenge-stage'
  )].some(visible);
  const editorElement = () => [...document.querySelectorAll('#prompt-textarea[contenteditable="true"], textarea#prompt-textarea, [role="textbox"][contenteditable="true"][aria-label="Ask ChatGPT"]')].find(visible);
  const hasTurns = () => assistants().length || document.querySelector('[data-message-author-role="user"]') ||
    turnHeadings("You said:").length || turnHeadings("ChatGPT said:").length;
  const attachmentSelector = '[data-testid="attachment-preview"], [data-testid="file-thumbnail"]';
  const removeAttachmentSelector = 'button[aria-label^="Remove "]';
  function attachmentCards(root = document) {
    const cards = [...root.querySelectorAll(attachmentSelector)];
    for (const remove of root.querySelectorAll(removeAttachmentSelector)) {
      if (cards.some(card => card.contains(remove))) continue;
      const name = remove.getAttribute("aria-label").slice("Remove ".length);
      // Current native image cards have no test id; bind thumbnail and Remove by the same filename.
      for (let card = remove.parentElement; card && card !== root; card = card.parentElement) {
        const images = [...card.querySelectorAll("img")];
        const buttons = [...card.querySelectorAll(removeAttachmentSelector)];
        if (buttons.length > 1) break;
        if (buttons.length === 1 && images.some(image => image.alt === name)) {
          cards.push(card);
          break;
        }
      }
    }
    return [...new Set(cards)].sort((a, b) => {
      if (a === b || typeof a.compareDocumentPosition !== "function") return 0;
      return a.compareDocumentPosition(b) & 2 ? 1 : -1;
    });
  }
  function uploadDomDiagnostics() {
    const counts = {editor_form: false, file_inputs: 0, form_file_inputs: 0, image_inputs: 0,
      form_image_inputs: 0, multiple_image_inputs: 0, unrestricted_inputs: 0, attachment_cards: 0};
    const queryAll = (root, selector) => {
      try { return [...root.querySelectorAll(selector)]; } catch { return []; }
    };
    let form = null;
    try {
      const editor = editorElement();
      form = editor?.closest("form") || null;
    } catch {}
    counts.editor_form = !!form;
    const imageAccepts = new Set(["image/*", "image/png", "image/jpeg", "image/webp", ".png", ".jpg", ".jpeg", ".webp"]);
    const countInputs = (inputs, inForm = false) => {
      for (const input of inputs) {
        try { if (input.disabled) continue; } catch { continue; }
        const fileKey = inForm ? "form_file_inputs" : "file_inputs";
        counts[fileKey] = Math.min(10000, counts[fileKey] + 1);
        let accept = null;
        try { if (typeof input.accept === "string") accept = input.accept; } catch {}
        const accepts = accept?.toLowerCase().split(",").map(value => value.trim()) || [];
        const image = accepts.some(value => imageAccepts.has(value));
        if (image) {
          const imageKey = inForm ? "form_image_inputs" : "image_inputs";
          counts[imageKey] = Math.min(10000, counts[imageKey] + 1);
          if (!inForm) try {
            if (input.multiple) counts.multiple_image_inputs = Math.min(10000, counts.multiple_image_inputs + 1);
          } catch {}
        }
        if (!inForm && accept !== null && accept.trim() === "")
          counts.unrestricted_inputs = Math.min(10000, counts.unrestricted_inputs + 1);
      }
    };
    countInputs(queryAll(document, 'input[type="file"]'));
    if (form) countInputs(queryAll(form, 'input[type="file"]'), true);
    counts.attachment_cards = Math.min(10000, attachmentCards(form || document).length);
    return counts;
  }
  const attachmentsPresent = () => [...document.querySelectorAll('input[type="file"]')].some(input => input.files?.length) ||
    document.querySelector('[data-testid="file-upload-progress"], ' + attachmentSelector) ||
    [...(editorElement()?.closest("form")?.querySelectorAll(removeAttachmentSelector + ', img, [role="progressbar"], [aria-busy="true"]') || [])].some(visible);
  function ownedUploads(job) {
    return uploadBinding && uploadBinding.jobId === job?.job_id && uploadBinding.path === location.pathname &&
      uploadBinding.editor === editorElement() && uploadBinding.names.join("\n") === (job.images || []).map(image => image.name).join("\n");
  }
  function verifiedUploadCards(job) {
    if (!ownedUploads(job)) return false;
    const scope = uploadBinding.scope;
    if (attachmentCards().some(card => !scope.contains(card)) ||
        [...document.querySelectorAll('input[type="file"]')].some(input => input.files?.length && !scope.contains(input)))
      throw new Error("Unexpected attachments outside this job's composer");
    if (scope.querySelector('[data-testid="file-upload-progress"], [role="progressbar"], [aria-busy="true"]')) return null;
    if (scope.querySelector('[role="alert"], [data-testid="file-upload-error"]'))
      throw new Error("Native attachment error; inspect the unsent draft");
    // These markers are checked conservatively. Unknown native UI is NOT proof
    // of readiness; live compatibility must be verified separately from mocks.
    const cards = attachmentCards(scope).filter(visible);
    if ([...scope.querySelectorAll("img")].some(image => visible(image) && !cards.some(card => card.contains(image))))
      throw new Error("Unrecognized attachment thumbnail; inspect the unsent draft");
    const removes = [...scope.querySelectorAll(removeAttachmentSelector)].filter(visible);
    if (removes.length > uploadBinding.names.length)
      throw new Error("Unexpected attachment controls in this job's composer; inspect the unsent draft");
    if (cards.length !== uploadBinding.names.length) return null;
    const valid = cards.every((card, index) => {
      const name = uploadBinding.names[index];
      const labels = [card.textContent, card.getAttribute("aria-label"), card.getAttribute("title"),
        ...[...card.querySelectorAll("img")].map(img => img.alt)].filter(Boolean).join(" ");
      const exactName = labels.split(/\s+/).includes(name);
      const remove = [...card.querySelectorAll("button")].some(button => visible(button) && !button.disabled &&
        button.getAttribute("aria-label") === `Remove ${name}`);
      const thumbnail = [...card.querySelectorAll("img")].some(img => visible(img) && img.complete && img.naturalWidth > 0);
      return exactName && remove && thumbnail;
    });
    return valid ? cards : null;
  }
  function uploadsReady(job) {
    return !!verifiedUploadCards(job);
  }
  async function clearPreflightUploads(job, editor) {
    const path = location.pathname;
    const remaining = {...job, images: [...(job.images || [])]};
    const inspectEmptyDraft = currentJob => {
      if (location.pathname !== path || editorElement() !== editor)
        throw new Error("Composer changed while removing this job's attachments; inspect the unsent draft");
      if (promptText(editor) !== "") throw new Error("Preserve composer text while clearing test uploads; nothing was submitted");
      const current = inspect(currentJob, true);
      if (promptText(current) !== "") throw new Error("Preserve composer text while clearing test uploads; nothing was submitted");
      return current;
    };
    inspectEmptyDraft(remaining);
    while (remaining.images.length) {
      if (!ownedUploads(remaining))
        throw new Error("Composer changed while removing this job's attachments; inspect the unsent draft");
      inspectEmptyDraft(remaining);
      const cards = verifiedUploadCards(remaining);
      if (!cards) throw new Error("This job's attachments are no longer verified; inspect the unsent draft");
      const remove = [...cards[0].querySelectorAll("button")].find(button => visible(button) && !button.disabled &&
        button.getAttribute("aria-label") === `Remove ${remaining.images[0].name}`);
      if (!remove) throw new Error("Native Remove control unavailable; inspect the unsent draft");
      const next = {...remaining, images: remaining.images.slice(1)};
      const previousNames = uploadBinding.names;
      remove.click();
      await waitFor(() => {
        if (!ownedUploads(remaining))
          throw new Error("Composer changed while removing this job's attachments; inspect the unsent draft");
        inspectEmptyDraft(remaining);
        // React removes cards asynchronously. Keep the old binding until that card disappears.
        const stillPresent = attachmentCards(uploadBinding.scope).filter(visible).some(card =>
          [...card.querySelectorAll("button")].some(button =>
            button.getAttribute("aria-label") === `Remove ${remaining.images[0].name}`));
        if (stillPresent) { verifiedUploadCards(remaining); return false; }
        uploadBinding.names = next.images.map(image => image.name);
        inspectEmptyDraft(next);
        const ready = next.images.length ? uploadsReady(next) : !attachmentsPresent();
        if (!ready) uploadBinding.names = previousNames;
        return ready;
      }, "Owned uploads were not fully removed; inspect the unsent draft");
      remaining.images = next.images;
    }
    if (location.pathname !== path || editorElement() !== editor)
      throw new Error("Composer changed after upload cleanup; inspect the unsent draft");
    uploadBinding = null;
    inspectEmptyDraft({...job, images: []});
  }
  async function uploadImages(job) {
    const images = job.images || [];
    if (!Array.isArray(images) || !["create", "edit"].includes(job.mode || "create") ||
        (job.mode === "edit" && !images.some(image => image.role === "source")) ||
        ((job.mode || "create") === "create" && images.some(image => image.role === "source")))
      throw new Error("Invalid create/edit image roles");
    if (!images.length) return;
    const editor = inspect(job);
    const scope = editor.closest("form");
    if (!scope) throw new Error("Native upload composer form unavailable; nothing uploaded");
    const accepts = (input, image) => (input.accept || "").split(",").map(value => value.trim().toLowerCase()).some(value =>
      value === "image/*" || value === image.mime || value === "." + image.name.split(".").at(-1) ||
      (value === ".jpeg" && image.mime === "image/jpeg"));
    const compatible = [...scope.querySelectorAll('input[type="file"]')].filter(input => !input.disabled &&
      (images.length === 1 || input.multiple === true) && images.every(image => accepts(input, image)));
    // ChatGPT can mount both a generic document uploader and an image-only uploader.
    const imageExtensions = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".svg", ".ico"]);
    const acceptTokens = input => (input.accept || "").split(",").map(value => value.trim().toLowerCase()).filter(Boolean);
    const imageToken = value => /^image\/[a-z0-9.+*-]+$/.test(value) || imageExtensions.has(value);
    const concreteImageToken = value => imageExtensions.has(value) || (/^image\/[a-z0-9.+-]+$/.test(value) && !value.includes("*"));
    const imageOnly = compatible.filter(input => {
      const tokens = acceptTokens(input);
      return tokens.length > 0 && tokens.every(imageToken);
    });
    // Prefer one typed picker over image/*. If every image-only picker is
    // image/*, keep the single multi-file picker and ignore the one-file picker.
    let inputs = compatible.length === 1 ? compatible : imageOnly;
    if (inputs.length > 1) {
      const typed = inputs.filter(input => acceptTokens(input).some(concreteImageToken));
      if (typed.length === 1) inputs = typed;
      else if (typed.length === 0) {
        const multi = inputs.filter(input => input.multiple === true);
        if (multi.length === 1) inputs = multi;
      }
    }
    if (inputs.length !== 1) {
      const typedCount = imageOnly.filter(input => acceptTokens(input).some(concreteImageToken)).length;
      const detail = imageOnly.length > 1 ? `, typed=${typedCount}, wildcard=${imageOnly.length - typedCount}` : "";
      throw new Error(`Native image file input missing, ambiguous or incompatible; compatible=${compatible.length}, image_only=${imageOnly.length}${detail}; nothing uploaded`);
    }
    const input = inputs[0], transfer = new DataTransfer();
    let total = 0;
    for (const [index, image] of images.entries()) {
      if (image.order !== index + 1 || !["source", "reference"].includes(image.role) ||
          typeof image.description !== "string" || !image.description.trim() || image.description.length > 200 ||
          !/^input-\d{3,}(?:-[a-f0-9]{32})?\.(png|jpg|webp)$/.test(image.name) ||
          !["image/png", "image/jpeg", "image/webp"].includes(image.mime) ||
          !Number.isInteger(image.bytes) || image.bytes < 1 || image.bytes > 8 * 1024 * 1024 ||
          typeof image.data_base64 !== "string" || image.data_base64.length !== 4 * Math.ceil(image.bytes / 3))
        throw new Error("Invalid ordered image input; nothing uploaded");
      total += image.bytes;
      if (total > 8 * 1024 * 1024) throw new Error("Inputs exceed the 8 MiB Bridge transport budget");
      const bytes = Uint8Array.from(atob(image.data_base64), char => char.charCodeAt(0));
      const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
        .map(byte => byte.toString(16).padStart(2, "0")).join("");
      if (bytes.length !== image.bytes || digest !== image.sha256) throw new Error("Input byte integrity check failed");
      transfer.items.add(new File([bytes], image.name, {type: image.mime}));
    }
    inspect(job); // Preserve any draft/attachments introduced while decoding.
    uploadBinding = {jobId: job.job_id, path: location.pathname, editor, scope, names: images.map(image => image.name)};
    input.files = transfer.files;
    if (input.files.length !== images.length || [...input.files].some((file, index) => file.name !== images[index].name))
      throw new Error("Native file input did not accept the ordered images");
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.dispatchEvent(new Event("change", {bubbles: true}));
    await waitFor(() => { inspect(job, true); return uploadsReady(job); }, "Native uploads not verified ready; inspect the unsent draft");
  }
  function bindInspectedPreflight(job) {
    const images = job.images || [], editor = editorElement(), scope = editor?.closest("form");
    if (job.preflight_only !== true || job.clear_preflight_uploads !== true || !images.length ||
        location.origin !== "https://chatgpt.com" || location.pathname !== "/" ||
        new URL(location.href).searchParams.get("temporary-chat") === "true" ||
        hasTurns() || busy() || !visible(editor) || !scope || promptText(editor) !== "" ||
        images.some((image, index) => image.order !== index + 1 || image.data_base64 !== undefined ||
          !/^input-\d{3,}(?:-[a-f0-9]{32})?(?:\([1-9]\d{0,5}\))?\.(png|jpg|webp)$/.test(image.name) || !/^[a-f0-9]{64}$/.test(image.sha256)) ||
        new Set(images.map(image => image.name)).size !== images.length)
      throw new Error("Inspected preflight draft changed; nothing was uploaded or removed");
    const count = attachmentCards(scope).filter(visible).length;
    // An explicitly inspected cleanup may resume only a remaining ordered suffix, never arbitrary files.
    if (!count || count > images.length || (count !== images.length && job.preflight_cleanup_resumed !== true))
      throw new Error("Existing preflight attachments do not exactly match; nothing was removed");
    const remaining = {...job, images: images.slice(-count)};
    uploadBinding = {jobId: job.job_id, path: location.pathname, editor, scope, names: remaining.images.map(image => image.name)};
    inspect(remaining, true);
    if (!uploadsReady(remaining)) throw new Error("Existing preflight attachments do not exactly match; nothing was removed");
    return remaining;
  }
  function idleEditor(job) {
    if (location.origin !== "https://chatgpt.com") throw new Error("Wrong site");
    if (verificationRequired()) throw new Error("Owner action required: complete verification in ChatGPT. Nothing was submitted.");
    if (new URL(location.href).searchParams.get("temporary-chat") === "true")
      throw new Error("Use a normal ChatGPT chat, not temporary chat. Nothing was submitted.");
    const editor = editorElement();
    if (!visible(editor)) throw new Error("ChatGPT composer unavailable. Nothing was submitted.");
    if (busy() || (promptText(editor) && !matchingDraft(job, editor)))
      throw new Error("Preserve the draft or running work. Nothing was submitted.");
    if (attachmentsPresent())
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
  async function reportPhase(job, phase, chatPath = "") {
    const receipt = await chrome.runtime.sendMessage({type: "image-phase", jobId: job.job_id, phase,
      ...(chatPath ? {chatPath} : {})});
    if (receipt?.error) throw new Error("Durable lifecycle receipt failed; inspect ChatGPT and do not retry");
  }
  async function prepare(job) {
    if (job?.expected_model !== "Create image") throw new Error("Native image mode is Create image");
    // React may briefly unmount the composer just after an image completes.
    // Wait for that UI, without navigating or clearing an unseen draft.
    await waitFor(() => visible(editorElement()) && editorElement(), "ChatGPT composer unavailable");
    let editor = idleEditor(job);
    if (hasTurns()) {
      const newChat = [...document.querySelectorAll('button[aria-label="New chat"]')].find(visible) ||
        [...document.querySelectorAll("button")].find(el => visible(el) && normalizedText(el.textContent) === "New chat");
      if (!newChat) throw new Error("Native New chat control unavailable. Nothing was submitted.");
      newChat.click();
      await waitFor(() => !hasTurns() && visible(editorElement()) && editorElement(), "Fresh chat did not become ready");
      editor = idleEditor(job);
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
    return {fresh: true, model: "Create image", input_protocol: 4, idle: true};
  }
  function inspect(job, uploading = false) {
    if (location.origin !== "https://chatgpt.com") throw new Error("Wrong site");
    if (verificationRequired()) throw new Error("Owner action required: complete verification in ChatGPT. Nothing was submitted.");
    const editor = editorElement();
    if (!visible(editor) || !visible(imageChip(editor)))
      throw new Error("Select native Create image in a normal fresh chat first. Plain chat and temporary chat are not image mode.");
    if (job.expected_model !== "Create image")
      throw new Error("Visible model label does not match expected_model. Native image mode is Create image.");
    if (busy() || assistants().length || document.querySelector('[data-message-author-role="user"]') ||
        turnHeadings("You said:").length || turnHeadings("ChatGPT said:").length ||
        (promptText(editor) && !matchingDraft(job, editor)))
      throw new Error("Use a fresh empty chat with no draft or running work. Nothing was submitted.");
    if (attachmentsPresent() && !(ownedUploads(job) && (uploading || uploadsReady(job))))
      throw new Error("Remove existing attachments before using the image worker");
    if (!uploading && ownedUploads(job) && !uploadsReady(job))
      throw new Error("This job's native attachments are no longer verified ready");
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
    let clickedAt = 0;
    const confirmation = event => {
      if (event.isTrusted) {
        confirmed = true;
        clickedAt = clickedAt || Date.now();
      }
    };
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
        if (confirmed && clickedAt && Date.now() - clickedAt >= 20000)
          throw new Error("Deletion did not leave this chat; saved image is safe, do not repeat automatically");
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
            clickedAt = Date.now();
            finalDelete.click();
          }
        }
      }
      throw new Error("Deletion confirmation timed out; saved image is safe, do not repeat automatically");
    } finally { finalDelete.removeEventListener("click", confirmation, {capture: true}); }
  }
  async function run(job, collectOnly = false) {
    let submitted = collectOnly;
    let promptBinding = null;
    try {
      if ((job.preflight_only !== undefined && typeof job.preflight_only !== "boolean") ||
          (job.clear_preflight_uploads !== undefined &&
            (typeof job.clear_preflight_uploads !== "boolean" ||
              (job.clear_preflight_uploads === true && job.preflight_only !== true))))
        throw new Error("clear_preflight_uploads is valid only as a boolean on an upload preflight");
      if (job.preflight_cleanup_only !== undefined && (typeof job.preflight_cleanup_only !== "boolean" ||
          (job.preflight_cleanup_only && (collectOnly || job.preflight_only !== true || job.clear_preflight_uploads !== true))))
        throw new Error("Invalid cleanup-only preflight");
      if (job.preflight_cleanup_resumed !== undefined && (typeof job.preflight_cleanup_resumed !== "boolean" ||
          (job.preflight_cleanup_resumed && job.preflight_cleanup_only !== true)))
        throw new Error("Invalid inspected cleanup resume");
      const prompt = jobPrompt(job);
      if (collectOnly) {
        if (job.output_binding_revision !== undefined && job.output_binding_revision !== 2)
          throw new Error("Unsupported output prompt binding revision; image was not collected");
        if (location.origin !== "https://chatgpt.com" || job.expected_model !== "Create image")
          throw new Error("Wrong site or model; existing image was not collected");
        if (job.collect_only && location.pathname !== job.recovery_chat_path)
          throw new Error("Existing result chat does not match this inspected job; nothing was submitted");
        if (verificationRequired() || busy() || turnHeadings("You said:").length !== 1 ||
            turnHeadings("ChatGPT said:").length !== 1 ||
            (job.visible_output_only === true && !outputImages().length))
          throw new Error(job.visible_output_only === true
            ? "Finished assistant image is not visible; nothing was submitted"
            : "Inspect the completed single-turn conversation before collecting; nothing was submitted");
        promptBinding = originalPromptBinding(job);
        if (typeof job.prompt !== "string" || (!promptBinding.root_match && !promptBinding.exact_matching_descendant_count))
          throw new Error("Existing conversation does not match this job's prompt; image was not collected");
      } else {
        const inputJob = job.preflight_cleanup_only === true ? bindInspectedPreflight(job) : job;
        if (job.preflight_cleanup_only !== true)
          await uploadImages(job);
        const editor = inspect(inputJob);
        if (job.preflight_only === true) {
          const preflightUploadsCleared = job.clear_preflight_uploads === true;
          if (preflightUploadsCleared) await clearPreflightUploads(inputJob, editor);
          const receipt = await chrome.runtime.sendMessage({type: "image-result", jobId: job.job_id,
            preflightReady: true, ...(preflightUploadsCleared ? {preflightUploadsCleared: true} : {})});
          if (receipt?.error) throw new Error("Preflight receipt unavailable; inspect this unsent draft, do not repeat automatically");
          return; // No text insertion, Send lookup/click, generation, fetch or deletion.
        }
        editor.focus();
        // A new explicit request may reuse only its exact unsent image draft.
        if (!matchingDraft(job, editor)) {
          if (editor instanceof HTMLTextAreaElement) {
            Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(editor, prompt);
            editor.dispatchEvent(new Event("input", {bubbles: true}));
          } else {
            // insertText enters text through the contenteditable editor, not its HTML.
            if (!document.execCommand("insertText", false, prompt)) throw new Error("Editor rejected text insertion");
            editor.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: prompt}));
          }
        }
        const send = await waitFor(() => {
          const current = editorElement();
          if (!visible(current) || !visible(imageChip(current))) return null;
          if (promptText(current) !== normalizedText(prompt))
            throw new Error("Composer text changed; not submitted");
          inspect(job);
          return [...document.querySelectorAll('[data-testid="send-button"], button[aria-label="Send"], button[aria-label="Send prompt"]')]
            .find(button => visible(button) && !button.disabled);
        }, "Native send button unavailable; not submitted");
        // Awaiting the control yields to native UI updates. Recheck the draft
        // and every upload once more before the synchronous final click.
        inspect(job);
        if (!visible(send) || send.disabled) throw new Error("Native send control changed; not submitted");
        submitted = true;  // Persist uncertainty before the click. From here, never replay.
        await reportPhase(job, "submit_attempted");
        send.click();
      }
      const deadline = Date.now() + 15 * 60 * 1000;
      let previous = "", stable = 0;
      let remoteStarted = collectOnly;
      while (Date.now() < deadline) {
        await sleep(2500);
        if (verificationRequired()) throw new Error("Owner action required: complete verification and inspect ChatGPT before any new request.");
        const livePath = /^\/c\/[a-f0-9-]{36}$/.test(location.pathname) ? location.pathname : "";
        if (!remoteStarted && livePath && (busy() || hasTurns() || assistants().length || outputImages().length)) {
          await reportPhase(job, "remote_started", livePath);
          remoteStarted = true;
        }
        const images = outputImages();
        if (!images.length || busy()) { stable = 0; continue; }
        if (images.length > 4) throw new Error("More than four assistant images; preserve chat and inspect outputs");
        const sources = images.map(img => img.currentSrc || img.src);
        const signature = JSON.stringify(sources);
        stable = signature === previous ? stable + 1 : 0;
        previous = signature;
        if (stable < 2) continue;
        const path = location.pathname;
        const outputs = [];
        let total = 0;
        for (const source of sources) {
          // Read only assets displayed in this assistant response, never auth/API data.
          const url = new URL(source, location.href);
          if (!["https:", "blob:"].includes(url.protocol)) throw new Error("Unsupported displayed image source");
          const response = await fetch(url.href, {signal: AbortSignal.timeout(30000)});
          if (!response.ok) throw new Error("Displayed image could not be read; preserve the existing chat");
          const blob = await response.blob();
          total += blob.size;
          if (!/^image\/(png|jpeg|webp)(;|$)/i.test(blob.type) || total > 25 * 1024 * 1024)
            throw new Error("Generated assets must be supported images under 25 MiB combined; preserve chat");
          const imageBase64 = await new Promise((resolve, reject) => {
            const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(",")[1]);
            reader.onerror = reject; reader.readAsDataURL(blob);
          });
          outputs.push(imageBase64);
        }
        if (path !== location.pathname || busy() || JSON.stringify(outputImages().map(img => img.currentSrc || img.src)) !== signature)
          throw new Error("Existing result changed during collection; preserve chat and do not regenerate");
        if (!collectOnly) {
          if (!remoteStarted) {
            await reportPhase(job, "remote_started", path);
            remoteStarted = true;
          }
          await reportPhase(job, "result_captured", path);
        }
        cleanupTarget = job.preserve_chat || outputs.length > 1 ? null : {jobId: job.job_id, path, prompt};
        const result = await chrome.runtime.sendMessage({type: "image-result", jobId: job.job_id,
          ...(outputs.length === 1 ? {imageBase64: outputs[0]} : {imagesBase64: outputs}), chatPath: path,
          ...(job.collect_only && promptBinding ? {promptBinding} : {})});
        if (result?.error) throw new Error("Image result could not be saved. Inspect ChatGPT; do not regenerate.");
        return;
      }
      // Name what the page looked like, so a finished image the detector missed is distinguishable from a slow one.
      throw new Error("Timed out; generation may still complete. Inspect ChatGPT before resubmitting. DOM: " + JSON.stringify(resultDomDiagnostics()));
    } catch (error) {
      await chrome.runtime.sendMessage({type: "image-result", jobId: job.job_id,
        ...(job.collect_only && promptBinding ? {promptBinding} : {}),
        error: (collectOnly ? "Existing submitted-job recovery failed. " : submitted ? "Submission attempted. " : "Not submitted. ") + error.message}).catch(() => {});
    } finally { running = false; uploadBinding = null; }
  }
  const listener = (message, _sender, reply) => {
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
    if (message.type === "image-identity") {
      let client_id = "";
      try {
        const stored = sessionStorage.getItem("gpt-bridge-pair");
        if (typeof stored === "string" && /^[a-f0-9-]{36}$/.test(stored)) client_id = stored;
      } catch (_) {}
      reply({client_id});
      return;
    }
    if (message.type === "image-bind") {
      try {
        if (typeof message.clientId === "string" && /^[a-f0-9-]{36}$/.test(message.clientId))
          sessionStorage.setItem("gpt-bridge-pair", message.clientId);
      } catch (_) {}
      reply({ok: true});
      return;
    }
    if (message.type === "image-inspect") {
      try {
        if (typeof message.clientId === "string" && /^[a-f0-9-]{36}$/.test(message.clientId))
          sessionStorage.setItem("gpt-bridge-pair", message.clientId);
      } catch (_) {}
      let idle = false;
      try {
        if (running) throw new Error("Content worker already running");
        idleEditor();
        idle = true;
        const model = "Create image";
        inspect({expected_model: model});
        reply({fresh: true, model, input_protocol: 4, idle, upload_dom: uploadDomDiagnostics(), result_dom: resultDomDiagnostics(), prompt_dom: promptDomDiagnostics()});
      } catch (error) { reply({error: !running && hasTurns() && !busy()
          ? "Existing conversation preserved; inspect its job result instead of submitting again" : error.message,
        input_protocol: 4, idle, upload_dom: uploadDomDiagnostics(), result_dom: resultDomDiagnostics(), prompt_dom: promptDomDiagnostics()}); }
      return;
    }
    if (!["image-job", "image-collect"].includes(message.type)) return;
    if (running) { reply({error: "Content worker already running"}); return; }
    running = true;
    reply({accepted: true});
    void run(message.job, message.type === "image-collect");
  };
  chrome.runtime.onMessage.addListener(listener);
  globalThis.__gptBridgeImageWorkerListener = listener;
})();
