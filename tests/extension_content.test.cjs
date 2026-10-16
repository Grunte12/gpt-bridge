const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {createHash, webcrypto} = require('node:crypto');
const vm = require('node:vm');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const contentSource = fs.readFileSync(path.join(root, 'extensions/chatgpt-image/content.js'), 'utf8');
const workerSource = fs.readFileSync(path.join(root, 'extensions/chatgpt-image/worker.js'), 'utf8');

function contentHarness({label = 'Create image', draft = '', busy = false, user = false, challenge = false, challengeAfterSend = false, newUi = false, inflateWhitespace = false, corruptInsertion = false, conversationTurns = null, conversationTurnsAfterSend = false, conversationBodies = [], assistantRoleNodes = false, assistantImageSources = null, assistantImageSequence = null, userImageSources = [], userPromptDescendants = [], conversationImageSources = null, imageMode = true, loseImageChipOnInsert = false, attachments = false, controls = true, temporaryChat = false, editorAvailable = true, editorDelayQueries = 0, hiddenRetainedEditor = false, imageReady = false, promptLinkBadge = false, waitForHumanDelete = false, confirmationResponse = null, onConfirmation = null, sendDelayQueries = 0, sendDisabledQueries = 0, hiddenFirstSend = false, changeDuringSend = null, changeAfterSendQueries = 1, uploadInput = true, uploadAccept = 'image/png,image/jpeg,image/webp', uploadMultiple = true, extraUploadInputs = 0, uploadInputSpecs = null, outsideUploadInput = null, formAvailable = true, attachmentCardCount = 0, uploadReadyAfterChecks = 0, uploadNeverReady = false, uploadReorder = false, uploadPartial = false, uploadError = false, uploadOutside = false, uploadMissingRemove = false, uploadMissingThumbnail = false, nativeUploadCards = false, reactClearsInputFiles = false, nativeAttachmentNames = [], nativeForeignOnUpload = '', nativeNoThumbnail = false, nativeAmbiguousContainer = false, nativeUnpairedThumbnail = false, changeDuringUpload = null, uploadRemovedBeforeSend = false, foreignTextAfterRemoveAt = 0, matchingDraftAfterRemoveAt = '', foreignAttachmentAfterRemoveAt = 0, removeProgressAfterClick = false, removeControlUnavailableAfter = Infinity, delayedNativeRemovePolls = 0, foreignTextAfterRemoveWaits = 0, matchingDraftAfterRemoveWaits = '', foreignAttachmentAfterRemoveWaits = 0, pathChangeAfterRemoveWaits = 0, staleListenerMarker = false, chatPath = '/c/123e4567-e89b-12d3-a456-426614174000'} = {}) {
  let now = 0;
  let listener;
  const contentListeners = [];
  let clicks = 0;
  let finalDeleteClicks = 0;
  let menuOpen = false;
  let busyState = busy;
  let challengeState = challenge;
  let controlsState = controls;
  let dialogOpen = false;
  let remainingEditorDelay = editorDelayQueries;
  let sendQueries = 0;
  let insertTextCalls = 0;
  let fetchCalls = 0;
  let fileReaderReads = 0;
  let uploadReadyChecks = 0;
  let uploadStarted = nativeAttachmentNames.length > 0;
  let uploadReadyState = nativeAttachmentNames.length > 0;
  let uploadRemoved = false;
  let uploadRemovalPending = false;
  let removeClickCount = 0;
  const removedUploadNames = [];
  let pendingNativeRemoval = null;
  let nativeRemovalWaitPolls = 0;
  let sendClicks = 0;
  let sendClickedWhenReady = false;
  let assistantImageQueries = 0;
  const fetchedUrls = [];
  const defaultImageSource = 'https://chatgpt.com/generated.png';
  const toDisplayedImage = source => ({src: source, currentSrc: source, complete: true,
    naturalWidth: 512, naturalHeight: 512, getClientRects: () => [{}]});
  const baseAssistantSources = assistantImageSources === null
    ? (imageReady ? [defaultImageSource] : []) : assistantImageSources;
  const userImages = userImageSources.map(toDisplayedImage);
  let userPromptDescendantNodes = [];
  userPromptDescendantNodes = userPromptDescendants.map(spec => {
    const attributes = new Set(Object.entries(spec.attributes || {})
      .filter(([, value]) => value !== false).map(([name]) => name));
    if (spec.inlinePill) attributes.add('data-inline-selection-pill');
    if (spec.systemHint) attributes.add('data-system-hint-type');
    if (spec.promptLink) attributes.add('data-prompt-link-href');
    const parentElement = {tagName: spec.parentTag || (spec.inButton ? 'BUTTON' : 'DIV')};
    return {
      ...('innerText' in spec ? {innerText: spec.innerText} : {}),
      ...('textContent' in spec ? {textContent: spec.textContent} : {}),
      ...('value' in spec ? {value: spec.value} : {}),
      tagName: spec.tagName || 'SPAN', parentElement,
      hasAttribute(name) { return attributes.has(name); },
      closest(selector) { return selector === 'button' && spec.inButton ? parentElement : null; },
      querySelector(selector) {
        const indices = spec.chipChildIndices || (Number.isInteger(spec.chipChildIndex) ? [spec.chipChildIndex] : []);
        return imageMode && /data-inline-selection-pill|data-prompt-link-href/.test(selector)
          ? indices.map(index => userPromptDescendantNodes[index]).find(node => node &&
            (node.hasAttribute('data-inline-selection-pill') || node.hasAttribute('data-prompt-link-href'))) || null
          : null;
      },
      querySelectorAll(selector) {
        const indices = spec.chipChildIndices || (Number.isInteger(spec.chipChildIndex) ? [spec.chipChildIndex] : []);
        return imageMode && /data-inline-selection-pill|data-prompt-link-href/.test(selector)
          ? indices.map(index => userPromptDescendantNodes[index]).filter(node => node &&
            (node.hasAttribute('data-inline-selection-pill') || node.hasAttribute('data-prompt-link-href'))) : [];
      },
      getClientRects: () => spec.visible === false ? [] : [{}]
    };
  });
  if (imageMode && !userPromptDescendantNodes.some(node =>
    node.hasAttribute('data-inline-selection-pill') || node.hasAttribute('data-prompt-link-href'))) {
    const attribute = promptLinkBadge ? 'data-prompt-link-href' : 'data-inline-selection-pill';
    userPromptDescendantNodes.push({innerText: 'Create image', tagName: 'SPAN', parentElement: {tagName: 'P'},
      hasAttribute(name) { return name === attribute; }, closest() { return null; },
      querySelector() { return null; }, querySelectorAll() { return []; },
      getClientRects: () => [{}]});
  }
  const allConversationImages = (conversationImageSources === null
    ? [...userImageSources, ...baseAssistantSources] : conversationImageSources).map(toDisplayedImage);
  const currentAssistantImages = () => {
    if (assistantImageSequence) {
      const index = Math.min(assistantImageQueries, assistantImageSequence.length - 1);
      assistantImageQueries++;
      return assistantImageSequence[index].map(toDisplayedImage);
    }
    return baseAssistantSources.map(toDisplayedImage);
  };
  const assistantMessage = {querySelectorAll(selector) { return selector === 'img' ? currentAssistantImages() : []; }};
  const uploadedFiles = nativeAttachmentNames.map(name => ({name, type: 'image/png', bytes: Uint8Array.from([1])}));
  const inputEvents = [];
  const composerEvents = [];
  const location = {origin: 'https://chatgpt.com', href: `https://chatgpt.com${temporaryChat ? '/?temporary-chat=true' : chatPath}`, pathname: chatPath};
  const currentConversationTurns = () => conversationTurns ||
    (conversationTurnsAfterSend && sendClicks > 0 ? ['You said:', 'ChatGPT said:'] : []);
  const hasConversation = () => user || currentConversationTurns().length > 0;
  const sent = [];
  const chip = {innerText: 'Create image', getClientRects: () => [{}]};
  const composerText = () => `${imageMode ? 'Create image' : ''}${draft ? (imageMode ? ' ' : '') + draft : ''}`;
  const bodyImageChip = selector => {
    if (!imageMode) return null;
    const attribute = promptLinkBadge ? 'data-prompt-link-href' : 'data-inline-selection-pill';
    return selector.includes(attribute)
      ? userPromptDescendantNodes.find(node => node.hasAttribute(attribute)) || chip : null;
  };
  class Textarea {
    constructor() { this._value = composerText(); this.disabled = false; }
    querySelector(selector) { return imageMode && (promptLinkBadge ? selector.includes('data-prompt-link-href') : selector.includes('data-inline-selection-pill')) ? chip : null; }
    get value() { return this._value; }
    focus() {}
    dispatchEvent(event) { composerEvents.push(event.type); }
    getClientRects() { return editorAvailable ? [{}] : []; }
    click() { clicks++; }
  }
  Object.defineProperty(Textarea.prototype, 'value', {get() { return this._value; }, set(v) { this._value = v; }});
  class ContentEditable {
    constructor() { this.innerText = composerText(); this.disabled = false; }
    querySelector(selector) { return imageMode && (promptLinkBadge ? selector.includes('data-prompt-link-href') : selector.includes('data-inline-selection-pill')) ? chip : null; }
    get textContent() { return this.innerText; }
    focus() {}
    dispatchEvent(event) { composerEvents.push(event.type); }
    getClientRects() { return editorAvailable ? [{}] : []; }
  }
  const editor = newUi ? new ContentEditable() : new Textarea();
  let form;
  const uploadCardCache = new WeakMap();
  const makeUploadCard = (file, index) => {
    if (uploadCardCache.has(file)) return uploadCardCache.get(file);
    const thumbnail = {alt: file.name, complete: !uploadMissingThumbnail, naturalWidth: uploadMissingThumbnail ? 0 : 32,
      getClientRects: () => [{}]};
    const card = {textContent: file.name, parentElement: form,
      getAttribute(name) { return name === 'title' ? file.name : null; },
      contains(element) { return card.removeControls.includes(element) || element === thumbnail; },
      querySelectorAll(selector) {
        if (selector === 'img') return nativeNoThumbnail ? [] : [thumbnail];
        if (selector === 'button' || selector.includes('button[aria-label^="Remove "]')) return card.removeControls;
        return [];
      },
      getClientRects: () => [{}], index};
    const remove = {disabled: false, parentElement: card,
      getAttribute(name) { return name === 'aria-label' ? `Remove ${file.name}` : null; },
      getClientRects: () => uploadMissingRemove || removeClickCount >= removeControlUnavailableAfter ? [] : [{}],
      click() {
        removeClickCount++;
        removedUploadNames.push(file.name);
        const input = fileInputs.find(item => item.files.includes(file));
        if (delayedNativeRemovePolls > 0) {
          pendingNativeRemoval = {file, input};
          nativeRemovalWaitPolls = 0;
        } else {
          if (input) input._files = input.files.filter(item => item !== file);
          uploadedFiles.splice(0, uploadedFiles.length, ...uploadedFiles.filter(item => item !== file));
        }
        if (foreignAttachmentAfterRemoveAt === removeClickCount) {
          const foreign = {name: 'foreign.png', type: 'image/png', bytes: Uint8Array.from([99])};
          if (input) input._files = [...input.files, foreign];
          uploadedFiles.push(foreign);
        }
        if (foreignTextAfterRemoveAt === removeClickCount) setEditorText(`${composerText()} unrelated text`);
        if (matchingDraftAfterRemoveAt)
          setEditorText(`Create image ${matchingDraftAfterRemoveAt}`);
        if (removeProgressAfterClick) uploadRemovalPending = true;
      }};
    const additionalRemove = {disabled: false, parentElement: card,
      getAttribute(name) { return name === 'aria-label' ? `Remove extra-${file.name}` : null; },
      getClientRects: () => [{}], click() { remove.click(); }};
    card.removeControls = nativeAmbiguousContainer ? [remove, additionalRemove] : [remove];
    uploadCardCache.set(file, card);
    return card;
  };
  const unpairedThumbnail = {alt: 'foreign-native.png', complete: true, naturalWidth: 32,
    getClientRects: () => [{}]};
  const unpairedNativeCard = {parentElement: form, querySelectorAll(selector) { return selector === 'img' ? [unpairedThumbnail] : []; },
    getClientRects: () => [{}]};
  unpairedThumbnail.parentElement = unpairedNativeCard;
  const inspectionCards = Array.from({length: attachmentCardCount}, () => ({getClientRects: () => [{}]}));
  const uploadCards = () => {
    if (inspectionCards.length) return inspectionCards;
    if (!uploadStarted || uploadRemoved || uploadNeverReady ||
        (!nativeAttachmentNames.length && uploadReadyChecks <= uploadReadyAfterChecks)) return [];
    let files = uploadedFiles.slice();
    if (uploadReorder) files.reverse();
    if (uploadPartial) files = files.slice(0, -1);
    return files.map(makeUploadCard);
  };
  const nativeRemoveControls = () => nativeUploadCards ? uploadCards().flatMap(card => card.removeControls) : [];
  const fileInput = (spec = {}, hasExistingFiles = attachments) => {
    const input = {type: 'file', accept: spec.accept ?? uploadAccept, multiple: spec.multiple ?? uploadMultiple,
      disabled: spec.disabled ?? false, name: spec.name, value: spec.value, _files: hasExistingFiles ? [{}] : [],
      get files() { return this._files; }, set files(value) { this._files = [...value]; },
      dispatchEvent(event) {
        inputEvents.push(event.type);
        if (event.type === 'change') {
          uploadStarted = true;
          uploadedFiles.splice(0, uploadedFiles.length, ...this._files);
          if (nativeForeignOnUpload) uploadedFiles.push({name: nativeForeignOnUpload, type: 'image/png', bytes: Uint8Array.from([99])});
          uploadReadyState = false;
          if (reactClearsInputFiles) this._files = [];
        }
      }};
    if (spec.throwAccept) Object.defineProperty(input, 'accept', {get() { throw new Error('accept unavailable'); }});
    return input;
  };
  const inputSpecs = uploadInputSpecs || Array.from({length: 1 + extraUploadInputs}, () => ({}));
  const fileInputs = uploadInput ? inputSpecs.map(spec => fileInput(spec)) : [];
  const outsideFileInput = outsideUploadInput ? fileInput(outsideUploadInput, false) : null;
  const finishPendingNativeRemoval = () => {
    if (!pendingNativeRemoval) return;
    const {file, input} = pendingNativeRemoval;
    if (input) input._files = input.files.filter(item => item !== file);
    uploadedFiles.splice(0, uploadedFiles.length, ...uploadedFiles.filter(item => item !== file));
    pendingNativeRemoval = null;
  };
  form = {contains(element) { return !uploadOutside && (fileInputs.includes(element) || uploadCards().includes(element) || nativeRemoveControls().includes(element)); },
    querySelectorAll(selector) {
      if (selector === 'input[type="file"]') return fileInputs;
      if (selector === 'img') return [...uploadCards().flatMap(card => card.querySelectorAll('img')),
        ...(nativeUnpairedThumbnail ? [unpairedThumbnail] : [])];
      if (selector.includes('button[aria-label^="Remove "]')) return nativeRemoveControls();
      if (nativeUploadCards && (selector.includes('[data-testid="attachment-preview"]') || selector.includes('[data-testid="file-thumbnail"]'))) return [];
      if (selector.includes('[data-testid="attachment-preview"]') || selector.includes('[data-testid="file-thumbnail"]')) return uploadCards();
      return [];
    },
    querySelector(selector) {
      if (uploadRemovalPending && selector.includes('[data-testid="file-upload-progress"]')) return {getClientRects: () => [{}]};
      if (selector.includes('[role="alert"]') || selector.includes('[data-testid="file-upload-error"]')) return uploadError ? {getClientRects: () => [{}]} : null;
      if (selector.includes('[data-testid="file-upload-progress"]') || selector.includes('[role="progressbar"]') || selector.includes('[aria-busy="true"]')) {
        uploadReadyChecks++;
        if (changeDuringUpload === 'text') setEditorText(`${composerText()} changed during upload`);
        if (changeDuringUpload === 'busy') busyState = true;
        if (changeDuringUpload === 'chip') imageMode = false;
        const cards = uploadCards();
        uploadReadyState = cards.length === uploadedFiles.length && cards.length > 0 && !uploadError && !uploadMissingRemove && !uploadMissingThumbnail;
        return uploadError ? null : (!uploadReadyState ? {getClientRects: () => [{}]} : null);
      }
      return null;
    }};
  unpairedNativeCard.parentElement = form;
  editor.closest = selector => selector === 'form' && formAvailable ? form : null;
  class FakeFile {
    constructor(parts, name, options = {}) {
      this.name = name;
      this.type = options.type || '';
      this.bytes = Uint8Array.from(parts.flatMap(part => [...part]));
    }
  }
  class FakeDataTransfer {
    constructor() {
      const files = [];
      this.items = {add(file) { files.push(file); }};
      Object.defineProperty(this, 'files', {get() { return files; }});
    }
  }
  const hiddenOldEditor = {value: 'completed conversation content', innerText: 'completed conversation content',
    querySelector() { return null; }, getClientRects: () => []};
  const setEditorText = value => { if (newUi) editor.innerText = value; else editor._value = value; };
  const send = {get disabled() { return sendQueries <= sendDelayQueries + sendDisabledQueries; }, getClientRects: () => [{}], click() { clicks++; sendClicks++; sendClickedWhenReady = (uploadReadyState && !uploadRemoved) || uploadedFiles.length === 0; }};
  const hiddenSend = {disabled: false, getClientRects: () => []};
  const picker = {textContent: label, getClientRects: () => [{}]};
  const button = (textContent, ariaLabel, isVisible, onClick = () => {}) => ({
    textContent, innerText: textContent, disabled: false, getAttribute(name) { return name === 'aria-label' ? ariaLabel : null; },
    getClientRects: () => isVisible() ? [{}] : [], click() { clicks++; onClick(); }
  });
  const newChatButton = button('New chat', 'New chat', () => controlsState && hasConversation(), () => {
    user = false; conversationTurns = []; conversationBodies = []; imageMode = false; draft = ''; setEditorText(''); menuOpen = false;
  });
  const filesButton = button('Add files and more', 'Add files and more', () => controlsState && !hasConversation() && !busyState && !challengeState && !challengeAfterSend && !attachments, () => { menuOpen = true; });
  const createImageButton = button('Create imageVisualize anything', null, () => controlsState && menuOpen, () => {
    imageMode = true; setEditorText('Create image'); menuOpen = false;
  });
  const moreButton = {...button('More', 'More', () => controlsState), dispatchEvent(event) {
    if (event.type === 'pointerdown' && event.bubbles && event.button === 0 &&
        event.pointerType === 'mouse' && event.isPrimary) {
      clicks++;
      menuOpen = true;
    }
  }};
  const deleteItem = {textContent: 'Delete', getClientRects: () => menuOpen ? [{}] : [], click() { clicks++; dialogOpen = true; menuOpen = false; }};
  const finalDeleteButton = {textContent: 'Delete chat', listeners: new Set(), getClientRects: () => dialogOpen ? [{}] : [],
    addEventListener(type, fn) { if (type === 'click') this.listeners.add(fn); },
    removeEventListener(type, fn) { if (type === 'click') this.listeners.delete(fn); },
    click(event = {isTrusted: false}) { clicks++; finalDeleteClicks++; for (const fn of this.listeners) fn(event); location.pathname = '/'; dialogOpen = false; }};
  const deleteDialog = {getClientRects: () => dialogOpen ? [{}] : [], querySelectorAll(selector) { return selector === 'button' ? [finalDeleteButton] : []; }};
  const conversation = {getClientRects: () => [{}], querySelectorAll(selector) {
    if (selector === 'img') return allConversationImages;
    if (selector === 'h4') return currentConversationTurns().map((textContent, index) => ({
      textContent, nextElementSibling: {
        innerText: conversationBodies[index] || '',
        querySelector(selector) { return bodyImageChip(selector); },
        querySelectorAll(selector) {
          if (selector === 'img') return textContent === 'You said:' ? userImages :
            textContent === 'ChatGPT said:' ? currentAssistantImages() : [];
          if (/data-inline-selection-pill|data-prompt-link-href/.test(selector))
            return userPromptDescendantNodes.filter(node => node.hasAttribute('data-inline-selection-pill') ||
              node.hasAttribute('data-prompt-link-href'));
          return selector === '*' && textContent === 'You said:' ? userPromptDescendantNodes : [];
        },
        getClientRects: () => [{}]
      },
      getClientRects: () => [{}]
    }));
    return [];
  }};
  const document = {
    querySelector(selector) {
      if ((newUi && selector.includes('[aria-label="Ask ChatGPT"]')) || selector.startsWith('#prompt-textarea')) {
        if (remainingEditorDelay > 0) { remainingEditorDelay--; return null; }
        return editor;
      }
      if (selector === '[data-testid="model-switcher-dropdown-button"]' || selector.includes('[aria-label="Select ChatGPT model"]')) return picker;
      if (selector === '[data-testid="stop-button"]' || selector.includes('button[aria-label="Stop"]')) return busyState ? {getClientRects: () => [{}]} : null;
      if (selector.includes('[aria-label="Conversation"]')) return conversation;
      if (selector === 'button[aria-label="New chat"]') return newChatButton;
      if (selector === 'button[aria-label="Add files and more"]') return filesButton;
      if (selector === 'button[aria-label="More"]') return moreButton;
      if (selector === '[role="dialog"]') return dialogOpen ? deleteDialog : null;
      if (selector.includes('input[type="file"]')) return fileInputs[0] || null;
      if (selector.includes('[data-testid="file-upload-progress"]') || selector.includes('[data-testid="attachment-preview"]') || selector.includes('[data-testid="file-thumbnail"]'))
        return uploadRemovalPending ? {getClientRects: () => [{}]} : nativeUploadCards
          ? (uploadedFiles.length && !uploadReadyState ? {getClientRects: () => [{}]} : null)
          : attachments ? {} : (uploadStarted && !uploadReadyState ? {getClientRects: () => [{}]} : uploadCards()[0] || null);
      if (selector === '[data-message-author-role="user"]') return user || currentConversationTurns().includes('You said:') ? {} : null;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === '[data-message-author-role="assistant"]')
        return assistantRoleNodes === 'always' || (assistantRoleNodes && sendClicks > 0) ? [assistantMessage] : [];
      if (selector === 'input[type="file"]') return [...fileInputs, ...(outsideFileInput ? [outsideFileInput] : [])];
      if (selector.includes('button[aria-label^="Remove "]')) return nativeRemoveControls();
      if (nativeUploadCards && (selector.includes('[data-testid="attachment-preview"]') || selector.includes('[data-testid="file-thumbnail"]'))) return [];
      if (selector.includes('[data-testid="attachment-preview"]') || selector.includes('[data-testid="file-thumbnail"]')) return uploadCards();
      if (selector.includes('[data-testid="send-button"]') || selector.includes('button[aria-label="Send"]')) {
        sendQueries++;
        if (uploadRemovedBeforeSend && sendQueries === changeAfterSendQueries) {
          uploadRemoved = true;
          uploadReadyState = false;
          for (const input of fileInputs) input._files = [];
        }
        if (sendQueries === changeAfterSendQueries) {
          if (changeDuringSend === 'text') setEditorText(`${composerText()} changed`);
          if (changeDuringSend === 'chip') imageMode = false;
          if (changeDuringSend === 'busy') busyState = true;
        }
        if (sendQueries <= sendDelayQueries) return [];
        return hiddenFirstSend ? [hiddenSend, send] : [send];
      }
      if (selector.includes('[role="textbox"]') || selector.includes('textarea#prompt-textarea'))
        return hiddenRetainedEditor ? [hiddenOldEditor, editor] : [editor];
      if (selector === '[role="menuitem"]') return [deleteItem];
      if (selector === '[role="dialog"]') return dialogOpen ? [deleteDialog] : [];
      if (selector.startsWith('button')) return [newChatButton, filesButton, createImageButton, moreButton].filter(item =>
        selector === 'button' || selector.includes(`aria-label="${item.getAttribute('aria-label')}"`));
      if (selector.includes('challenges.cloudflare.com') && (challengeState || (challengeAfterSend && clicks)))
        return [{getClientRects: () => [{}]}];
      if (selector.includes('h4') && !selector.startsWith('region'))
        return currentConversationTurns().map(textContent => ({textContent, getClientRects: () => [{}]}));
      return [];
    },
    execCommand(_cmd, _ui, value) {
      insertTextCalls++;
      let inserted = corruptInsertion ? value.replace('Create one image', 'Create one cat') : value;
      if (inflateWhitespace) inserted = inserted.replace(/\n\n/g, '\n\n\n\n\n');
      if (newUi) editor.innerText += inserted;
      else editor._value += inserted;
      if (loseImageChipOnInsert) imageMode = false;
      return true;
    }
  };
  const NativeDate = Date;
  class SimDate extends NativeDate { static now() { return now; } }
  const chrome = {runtime: {
    onMessage: {addListener(fn) { listener = fn; contentListeners.push(fn); }, hasListener(fn) { return contentListeners.includes(fn); }},
    async sendMessage(message) {
      sent.push(message);
      if (message.type === 'image-delete-prompt') return {ok: true};
      if (message.type === 'image-delete-confirmation') {
        onConfirmation?.(message);
        return typeof confirmationResponse === 'function' ? confirmationResponse(message) : (confirmationResponse || {});
      }
      return {};
    }
  }};
  const context = {
    chrome, document, location,
    HTMLTextAreaElement: Textarea, Event: class { constructor(type, init = {}) { this.type = type; Object.assign(this, init); } },
    InputEvent: class { constructor(type, init = {}) { this.type = type; Object.assign(this, init); } },
    File: FakeFile, DataTransfer: FakeDataTransfer, atob, crypto: webcrypto,
    PointerEvent: class { constructor(type, init = {}) { this.type = type; Object.assign(this, init); } }, Date: SimDate,
    setTimeout(fn, ms) {
      if (pendingNativeRemoval && ms === 100) {
        nativeRemovalWaitPolls++;
        if (foreignTextAfterRemoveWaits === nativeRemovalWaitPolls) setEditorText(`${composerText()} unrelated text`);
        if (matchingDraftAfterRemoveWaits) setEditorText(`Create image ${matchingDraftAfterRemoveWaits}`);
        if (foreignAttachmentAfterRemoveWaits === nativeRemovalWaitPolls) {
          const foreign = {name: 'foreign.png', type: 'image/png', bytes: Uint8Array.from([99])};
          const input = pendingNativeRemoval.input;
          if (input) input._files = [...input.files, foreign];
          uploadedFiles.push(foreign);
        }
        if (pathChangeAfterRemoveWaits === nativeRemovalWaitPolls) location.pathname = '/c/another-chat';
        if (nativeRemovalWaitPolls >= delayedNativeRemovePolls) finishPendingNativeRemoval();
      }
      if (waitForHumanDelete && ms === 250) { now += ms; setImmediate(fn); }
      else { now += ms; queueMicrotask(fn); }
      return 1;
    }, clearTimeout() {},
    URL, AbortSignal, async fetch(url) { fetchedUrls.push(url); fetchCalls++; return {ok: true, async blob() { return {type: 'image/png', size: 32}; }}; },
    FileReader: class { readAsDataURL() { fileReaderReads++; this.result = 'data:image/png;base64,cG5n'; this.onload(); } }
  };
  if (staleListenerMarker) context.__gptBridgeImageWorkerListener = () => {};
  vm.runInNewContext(contentSource, context, {filename: 'content.js'});
  return {receive: listener, sent, get contentListenerCount() { return contentListeners.length; }, rerunContent() { vm.runInNewContext(contentSource, context, {filename: 'content.js'}); },
    get clicks() { return clicks; }, get finalDeleteClicks() { return finalDeleteClicks; }, get sendClicks() { return sendClicks; },
    get sendQueries() { return sendQueries; }, get insertTextCalls() { return insertTextCalls; }, get composerEvents() { return composerEvents; },
    get fetchCalls() { return fetchCalls; }, get fetchedUrls() { return fetchedUrls; }, get fileReaderReads() { return fileReaderReads; },
    get sendClickedWhenReady() { return sendClickedWhenReady; }, get uploadedFiles() { return uploadedFiles; }, get fileInputs() { return fileInputs; }, get inputEvents() { return inputEvents; },
    get removeClicks() { return removeClickCount; },
    get removedUploadNames() { return removedUploadNames; },
    get uploadReadyState() { return uploadReadyState; }, get uploadReadyChecks() { return uploadReadyChecks; }, editor, location,
    clickMore() { moreButton.click(); }, get deleteMenuOpen() { return menuOpen; },
    setBusy(value) { busyState = value; }, setChallenge(value) { challengeState = value; },
    setControls(value) { controlsState = value; }, setConversationBodies(value) { conversationBodies = value; },
    confirmDelete() { for (const fn of finalDeleteButton.listeners) fn({isTrusted: true}); dialogOpen = false; location.pathname = '/'; },
    trustedClickClosesDialog() { for (const fn of finalDeleteButton.listeners) fn({isTrusted: true}); dialogOpen = false; },
    syntheticDeleteClick() { finalDeleteButton.click({isTrusted: false}); },
    closeDeleteDialog() { dialogOpen = false; },
    setFinalDeleteDisabled(value) { finalDeleteButton.disabled = value; },
    delayedPathChange() { setImmediate(() => { location.pathname = '/'; }); }};
}

async function startContent(harness, job = {job_id: 'job-1', expected_model: 'Create image', prompt: 'draw a cat'}) {
  let accepted;
  harness.receive({type: 'image-job', job}, {}, value => { accepted = value; });
  await new Promise(resolve => setImmediate(resolve));
  return accepted;
}

async function waitForContentResult(harness) {
  for (let i = 0; i < 50 && !harness.sent.some(message => message.type === 'image-result' &&
    (message.imageBase64 || message.error || message.preflightReady === true)); i++)
    await new Promise(resolve => setImmediate(resolve));
}

async function startCollect(harness, expectedModel = 'Create image', prompt = 'draw a cat', jobOptions = {}) {
  let accepted;
  harness.receive({type: 'image-collect', job: {job_id: 'job-collect', expected_model: expectedModel, prompt, ...jobOptions}}, {}, value => { accepted = value; });
  await new Promise(resolve => setImmediate(resolve));
  return accepted;
}

async function startPrepare(harness, expectedModel = 'Create image', prompt) {
  let result;
  const job = {expected_model: expectedModel};
  if (prompt !== undefined) job.prompt = prompt;
  harness.receive({type: 'image-prepare', job}, {}, value => { result = value; });
  await new Promise(resolve => setImmediate(resolve));
  return result;
}

function imageInput(order, role = 'reference', payload = [order, 17, 34, 51]) {
  const bytes = Buffer.from(payload);
  return {
    order,
    role,
    description: `${role} ${order}`,
    name: `input-${String(order).padStart(3, '0')}.png`,
    mime: 'image/png',
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    dimensions: {width: 1, height: 1},
    data_base64: bytes.toString('base64')
  };
}

async function primeArchiveTarget(overrides = {}) {
  const prompt = 'Create one image. Return a generated image, not just a description.\n\ndraw a cat';
  const h = contentHarness({newUi: true, user: true, conversationTurns: ['You said:', 'ChatGPT said:'],
    conversationBodies: [`Create image ${prompt}`], imageReady: true, promptLinkBadge: true, waitForHumanDelete: true, ...overrides});
  const accepted = await startCollect(h);
  assert.ok(accepted?.accepted);
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-result' && message.imageBase64); i++)
    await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.sent.some(message => message.type === 'image-result' && message.imageBase64), 'saved image receipt must exist before cleanup');
  return h;
}

async function requestDelete(harness, overrides = {}) {
  let result;
  harness.receive({type: 'image-delete', jobId: 'job-collect', chatPath: harness.location.pathname, ...overrides}, {}, value => { result = value; });
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  return result;
}

test('image preparation leaves an already-fresh native image chat unchanged', async () => {
  const h = contentHarness();
  const result = await startPrepare(h);
  assert.deepEqual({...result}, {fresh: true, model: 'Create image', input_protocol: 4, idle: true});
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.value, 'Create image');
});

test('inspection selects the visible composer when a hidden retained composer comes first', () => {
  const h = contentHarness({newUi: true, hiddenRetainedEditor: true});
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {fresh: true, model: 'Create image', input_protocol: 4, idle: true,
    upload_dom: {editor_form: true, file_inputs: 1, form_file_inputs: 1, image_inputs: 1, form_image_inputs: 1,
      multiple_image_inputs: 1, unrestricted_inputs: 0, attachment_cards: 0},
    result_dom: {assistant_role_nodes: 0, user_headings: 0, assistant_headings: 0,
      assistant_body_found: false, assistant_images: 0, conversation_images: 0, busy: false,
      chat_path: '/c/123e4567-e89b-12d3-a456-426614174000'},
    prompt_dom: {body_chars: 0, stripped_chars: 0, matched_chip_chars: 0, label_count: 0,
      starts_with_label: false, ends_with_label: false, labels: []}});
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.innerText, 'Create image');
});

test('image preparation turns a completed chat into a fresh native image chat through visible controls', async () => {
  const h = contentHarness({newUi: true, user: true, conversationTurns: ['You said:', 'ChatGPT said:'], imageMode: false, hiddenRetainedEditor: true});
  const result = await startPrepare(h);
  assert.deepEqual({...result}, {fresh: true, model: 'Create image', input_protocol: 4, idle: true});
  assert.equal(h.clicks, 3);
  assert.equal(h.editor.innerText, 'Create image');
});

test('image preparation waits for a temporarily unmounted composer and does not submit', async () => {
  const h = contentHarness({editorDelayQueries: 3});
  const result = await startPrepare(h);
  assert.deepEqual({...result}, {fresh: true, model: 'Create image', input_protocol: 4, idle: true});
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.value, 'Create image');
  assert.equal(h.sent.length, 0);
});

test('image preparation accepts only a matching unsent image draft', async () => {
  const prompt = 'draw a cat';
  const draft = `Create one image. Return a generated image, not just a description.\n\n${prompt}`;
  const h = contentHarness({draft});
  const result = await startPrepare(h, 'Create image', prompt);
  assert.deepEqual({...result}, {fresh: true, model: 'Create image', input_protocol: 4, idle: true});
  assert.equal(h.editor.value, `Create image ${draft}`);
  assert.equal(h.clicks, 0);
});

test('image preparation refuses drafts, running work, challenges, attachments, and wrong expected model', async () => {
  for (const [name, options, expectedModel] of [
    ['draft', {draft: 'keep this'}, 'Create image'],
    ['running work', {busy: true}, 'Create image'],
    ['challenge', {challenge: true}, 'Create image'],
    ['attachments', {attachments: true}, 'Create image'],
    ['temporary chat', {temporaryChat: true}, 'Create image'],
    ['missing composer', {editorAvailable: false}, 'Create image'],
    ['wrong expected model', {}, 'GPT-6 Thinking']
  ]) {
    const h = contentHarness(options);
    const originalText = h.editor.value;
    const result = await startPrepare(h, expectedModel);
    assert.ok(result?.error, `${name} should be refused`);
    assert.equal(h.clicks, 0, `${name} should not activate UI controls`);
    assert.equal(h.editor.value, originalText, `${name} should preserve the editor`);
  }
});

test('image preparation fails closed when visible new-chat or image-mode controls are unavailable', async () => {
  for (const options of [
    {user: true, conversationTurns: ['You said:'], controls: false},
    {controls: false, imageMode: false}
  ]) {
    const h = contentHarness(options);
    const originalText = h.editor.value;
    const result = await startPrepare(h);
    assert.ok(result?.error);
    assert.equal(h.clicks, 0);
    assert.equal(h.editor.value, originalText);
  }
});

test('delete requires a saved image receipt from this worker before it can target a chat', async () => {
  const h = contentHarness({newUi: true, user: true, conversationTurns: ['You said:', 'ChatGPT said:'],
    conversationBodies: ['Create image Create one image. Return a generated image, not just a description. draw a cat']});
  const result = await requestDelete(h);
  assert.match(result.error, /Only this worker's saved image chat can be deleted/);
  assert.equal(h.clicks, 0);
  assert.match(h.location.pathname, /^\/c\//);
});

test('delete opens exact native Delete confirmation after the saved image receipt but never clicks final Delete chat', async () => {
  const h = await primeArchiveTarget();
  const receipt = h.sent.find(message => message.type === 'image-result' && message.imageBase64);
  assert.equal(receipt.chatPath, h.location.pathname);
  assert.equal(receipt.jobId, 'job-collect');
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++)
    await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.sent.some(message => message.type === 'image-delete-prompt' && message.jobId === 'job-collect'));
  assert.equal(h.clicks, 2, 'only More and the menu Delete are clicked; final Delete chat remains human-confirmed');
  assert.match(h.location.pathname, /^\/c\//);
  h.confirmDelete(); // simulate the human's separate final action
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual({...result}, {deleted: true});
  assert.equal(h.clicks, 2, 'the final confirmation button was never clicked by the extension');
  const repeated = await requestDelete(h);
  assert.match(repeated.error, /Only this worker's saved image chat can be deleted/);
  assert.equal(h.clicks, 2);
});

test('More menu opens only from the native primary mouse pointerdown, not click()', () => {
  const h = contentHarness();
  h.clickMore();
  assert.equal(h.deleteMenuOpen, false);
  h.receive({type: 'image-delete'}, {}, () => {});
  assert.equal(h.deleteMenuOpen, false);
});

test('navigation without a trusted final Delete chat click refuses', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++) await new Promise(resolve => setImmediate(resolve));
  h.location.pathname = '/';
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.match(result.error, /without deletion confirmation/);
  assert.equal(h.clicks, 2);
});

test('an untrusted synthetic final Delete chat click does not authorize deletion', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++) await new Promise(resolve => setImmediate(resolve));
  h.syntheticDeleteClick();
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.match(result.error, /without deletion confirmation/);
  assert.equal(h.clicks, 3, 'one synthetic click plus the two automated menu clicks; no trusted action');
});

test('trusted user final click followed by path change passes', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++) await new Promise(resolve => setImmediate(resolve));
  h.confirmDelete();
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual({...result}, {deleted: true});
  assert.equal(h.clicks, 2, 'the final button is confirmed by a trusted user event, never extension-clicked');
});

test('trusted click may close dialog before delayed path change', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++) await new Promise(resolve => setImmediate(resolve));
  h.trustedClickClosesDialog();
  h.delayedPathChange();
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual({...result}, {deleted: true});
  assert.equal(h.clicks, 2);
});

test('one explicit MCP approval clicks final Delete once and completes cleanup', async () => {
  const h = await primeArchiveTarget({confirmationResponse: {confirmed: true}});
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 20 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual({...result}, {deleted: true});
  assert.equal(h.finalDeleteClicks, 1);
  assert.equal(h.clicks, 3, 'two menu activations plus one approved final click');
  assert.equal(h.sent.filter(message => message.type === 'image-delete-confirmation').length, 1,
    'the successful job-scoped approval is consumed once');
});

test('false MCP confirmation never clicks final Delete', async () => {
  const h = await primeArchiveTarget({confirmationResponse: {confirmed: false}, onConfirmation() { h.closeDeleteDialog(); }});
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 20 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.match(result.error, /Deletion was not confirmed/);
  assert.equal(h.finalDeleteClicks, 0);
  assert.equal(h.sent.filter(message => message.type === 'image-delete-confirmation').length, 1);
});

test('MCP approval fails closed if dialog, path, draft, or button state changed', async () => {
  const cases = [
    ['dialog', h => h.closeDeleteDialog()],
    ['path', h => { h.location.pathname = '/'; }],
    ['draft', h => { h.editor.innerText = 'Create image unsent draft'; }],
    ['disabled button', h => h.setFinalDeleteDisabled(true)]
  ];
  for (const [name, mutate] of cases) {
    let harness;
    harness = await primeArchiveTarget({confirmationResponse: {confirmed: true}, onConfirmation: () => mutate(harness)});
    let result;
    harness.receive({type: 'image-delete', jobId: 'job-collect', chatPath: harness.location.pathname}, {}, value => { result = value; });
    for (let i = 0; i < 20 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
    assert.ok(result?.error, `${name} change must fail closed`);
    assert.equal(harness.finalDeleteClicks, 0, `${name} change must not click final Delete`);
    assert.equal(harness.sent.filter(message => message.type === 'image-delete-confirmation').length, 1);
  }
});

test('delete refuses an unknown job or mismatched chat path without opening menus', async () => {
  for (const overrides of [{jobId: 'other-job'}, {chatPath: '/c/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}]) {
    const h = await primeArchiveTarget();
    const result = await requestDelete(h, overrides);
    assert.ok(result?.error);
    assert.equal(h.clicks, 0);
    assert.match(h.location.pathname, /^\/c\//);
  }
});

test('closing the native confirmation without changing chat path fails without a final Delete chat click', async () => {
  const h = await primeArchiveTarget();
  let result;
  h.receive({type: 'image-delete', jobId: 'job-collect', chatPath: h.location.pathname}, {}, value => { result = value; });
  for (let i = 0; i < 10 && !h.sent.some(message => message.type === 'image-delete-prompt'); i++)
    await new Promise(resolve => setImmediate(resolve));
  assert.ok(h.sent.some(message => message.type === 'image-delete-prompt'));
  h.closeDeleteDialog();
  for (let i = 0; i < 10 && result === undefined; i++) await new Promise(resolve => setImmediate(resolve));
  assert.match(result.error, /Deletion was not confirmed/);
  assert.equal(h.clicks, 2);
  assert.match(h.location.pathname, /^\/c\//);
});

test('delete refuses changed prompt, draft, running work, challenge, or unavailable controls', async () => {
  const cases = [
    ['changed prompt', h => h.setConversationBodies(['wrong prompt', 'assistant'])],
    ['draft', h => { h.editor.innerText = 'unsent draft'; }],
    ['running work', h => h.setBusy(true)],
    ['challenge', h => h.setChallenge(true)],
    ['missing controls', h => h.setControls(false)]
  ];
  for (const [name, mutate] of cases) {
    const h = await primeArchiveTarget();
    mutate(h);
    const result = await requestDelete(h);
    assert.ok(result?.error, `${name} must fail closed`);
    assert.equal(h.clicks, 0, `${name} must not click More or Archive`);
    assert.match(h.location.pathname, /^\/c\//);
  }
});

test('pairing inspection reports native Create image mode without touching the composer', () => {
  const h = contentHarness();
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.equal(result.fresh, true);
  assert.equal(result.model, 'Create image');
  assert.equal(result.input_protocol, 4);
  assert.equal(result.idle, true);
  assert.deepEqual(JSON.parse(JSON.stringify(result.upload_dom)), {
    editor_form: true, file_inputs: 1, form_file_inputs: 1, image_inputs: 1, form_image_inputs: 1,
    multiple_image_inputs: 1, unrestricted_inputs: 0, attachment_cards: 0
  });
  assert.equal(h.clicks, 0);
  assert.equal(h.sendQueries, 0);
  assert.deepEqual(h.inputEvents, []);
  assert.deepEqual(h.composerEvents, []);
  assert.equal(h.editor.value, 'Create image');
});

test('pairing inspection rejects a draft or blank model without submitting', () => {
  for (const options of [{draft: 'preserve this draft'}, {imageMode: false}]) {
    const h = contentHarness(options);
    const originalText = h.editor.value;
    let result;
    h.receive({type: 'image-inspect'}, {}, value => { result = value; });
    assert.match(result.error, /Preserve the draft or running work|Select native Create image/);
    assert.equal(result.input_protocol, 4);
    assert.equal(result.idle, options.draft ? false : true);
    assert.deepEqual(Object.keys(result.upload_dom).sort(), ['attachment_cards', 'editor_form', 'file_inputs',
      'form_file_inputs', 'form_image_inputs', 'image_inputs', 'multiple_image_inputs', 'unrestricted_inputs']);
    assert.equal(h.editor.value, originalText);
    assert.equal(JSON.stringify(result).includes('preserve this draft'), false, 'inspection does not return composer text');
    assert.equal(h.clicks, 0);
  }
});

test('upload DOM inspection counts only enabled inputs and stays scoped to the editor form', () => {
  const h = contentHarness({uploadInputSpecs: [
    {accept: 'image/*,.png', multiple: true, name: 'private-name.png', value: 'private-value'},
    {accept: '.jpg,.jpeg,image/webp', multiple: false},
    {accept: '', multiple: false},
    {accept: 'image/png', multiple: true, disabled: true}
  ], outsideUploadInput: {accept: 'image/webp', multiple: true, name: 'outside-private.png'}});
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });

  assert.equal(result.fresh, true);
  assert.deepEqual(JSON.parse(JSON.stringify(result.upload_dom)), {
    editor_form: true, file_inputs: 4, form_file_inputs: 3, image_inputs: 3, form_image_inputs: 2,
    multiple_image_inputs: 2, unrestricted_inputs: 1, attachment_cards: 0
  });
  assert.doesNotMatch(JSON.stringify(result.upload_dom), /private|outside|png|jpg|jpeg|webp|image\//i);
  assert.equal(h.clicks, 0);
  assert.equal(h.sendQueries, 0);
  assert.deepEqual(h.inputEvents, []);
});

test('upload DOM inspection returns safe counts without an editor and isolates property failures', () => {
  const noEditor = contentHarness({editorAvailable: false, uploadInputSpecs: [
    {accept: '.jpg', multiple: true}, {accept: '', multiple: false}
  ], outsideUploadInput: {accept: 'image/*', multiple: true}});
  let result;
  noEditor.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.match(result.error, /composer unavailable/);
  assert.deepEqual(JSON.parse(JSON.stringify(result.upload_dom)), {
    editor_form: false, file_inputs: 3, form_file_inputs: 0, image_inputs: 2, form_image_inputs: 0,
    multiple_image_inputs: 2, unrestricted_inputs: 1, attachment_cards: 0
  });

  const badProperty = contentHarness({uploadInputSpecs: [{throwAccept: true}]});
  badProperty.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.equal(result.fresh, true, 'diagnostics cannot turn a successful normal inspection into an error');
  assert.equal(result.upload_dom.file_inputs, 1);
  assert.equal(result.upload_dom.image_inputs, 0);
  assert.equal(badProperty.clicks, 0);
  assert.deepEqual(badProperty.inputEvents, []);
});

test('upload DOM diagnostics are included on inspection errors without changing error state', () => {
  const h = contentHarness({attachments: true, attachmentCardCount: 2});
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.match(result.error, /Remove existing attachments/);
  assert.deepEqual(JSON.parse(JSON.stringify(result.upload_dom)), {
    editor_form: true, file_inputs: 1, form_file_inputs: 1, image_inputs: 1, form_image_inputs: 1,
    multiple_image_inputs: 1, unrestricted_inputs: 0, attachment_cards: 2
  });
  assert.equal(result.idle, false);
  assert.equal(h.editor.value, 'Create image');
  assert.equal(h.clicks, 0);
  assert.deepEqual(h.inputEvents, []);
});

test('prompt DOM inspection counts exact visible edge labels and reports bounded semantic flags without text', () => {
  const uniquePromptText = 'private prompt marker that must not appear in diagnostics';
  const body = `Create image\n${uniquePromptText}\nCreate image`;
  const labels = [
    {innerText: 'Create image', tagName: 'SPAN', parentTag: 'DIV', inlinePill: true, systemHint: true},
    {innerText: 'Create image', tagName: 'SPAN', parentTag: 'BUTTON', promptLink: true, inButton: true},
    ...Array.from({length: 8}, () => ({innerText: 'Create image', tagName: 'SPAN', parentTag: 'P'})),
    {innerText: 'Create image', visible: false},
    {innerText: 'before Create image after'},
    {textContent: 'Create image'}
  ];
  const h = contentHarness({
    user: true, conversationTurns: ['You said:'], conversationBodies: [body], userPromptDescendants: labels
  });
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });

  const diagnostics = JSON.parse(JSON.stringify(result.prompt_dom));
  const normalizedBody = body.replace(/\s+/g, ' ').trim();
  assert.deepEqual(diagnostics, {
    body_chars: normalizedBody.length,
    stripped_chars: normalizedBody.replace('Create image', ' ').replace(/\s+/g, ' ').trim().length,
    matched_chip_chars: 'Create image'.length,
    label_count: 10,
    starts_with_label: true,
    ends_with_label: true,
    labels: [
      {tag: 'SPAN', parent_tag: 'DIV', inline_pill: true, system_hint: true,
        prompt_link: false, in_button: false, matched_chip: true},
      {tag: 'SPAN', parent_tag: 'BUTTON', inline_pill: false, system_hint: false,
        prompt_link: true, in_button: true, matched_chip: false},
      ...Array.from({length: 6}, () => ({tag: 'SPAN', parent_tag: 'P', inline_pill: false,
        system_hint: false, prompt_link: false, in_button: false, matched_chip: false}))
    ]
  });
  assert.equal(diagnostics.labels.length, 8, 'individual label details are capped at eight');
  assert.equal(JSON.stringify(result).includes(uniquePromptText), false, 'inspection never returns message text');
  assert.equal(h.clicks, 0);
  assert.equal(h.sendClicks, 0);
});

test('pairing inspection without a job refuses even an otherwise matching image draft', () => {
  const h = contentHarness({draft: 'Create one image. Return a generated image, not just a description.\n\ndraw a cat'});
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });
  assert.match(result.error, /Preserve the draft or running work/);
  assert.equal(result.input_protocol, 4);
  assert.equal(result.idle, false);
  assert.equal(h.clicks, 0);
});

test('read-only inspection reports idle state without changing drafts, busy work, attachments, or completed chats', () => {
  const cases = [
    ['completed chat without image mode', {newUi: true, user: true, conversationTurns: ['You said:', 'ChatGPT said:'], imageMode: false}, true,
      /Existing conversation preserved; inspect its job result instead of submitting again/],
    ['unrelated draft', {draft: 'private draft'}, false, /Preserve the draft or running work/],
    ['busy draft', {busy: true, draft: 'private draft'}, false, /Preserve the draft or running work/],
    ['existing attachment', {attachments: true}, false, /Remove existing attachments/]
  ];
  for (const [name, options, idle, reason] of cases) {
    const h = contentHarness(options);
    const originalText = h.editor.value;
    let result;
    h.receive({type: 'image-inspect'}, {}, value => { result = value; });
    assert.equal(result.input_protocol, 4, `${name} advertises the current protocol`);
    assert.equal(result.idle, idle, `${name} reports native composer idleness`);
    assert.match(result.error, reason, `${name} still fails the freshness check`);
    assert.equal(h.editor.value, originalText, `${name} state is preserved`);
    assert.equal(JSON.stringify(result).includes('private draft'), false, `${name} text is not returned`);
    assert.equal(h.clicks, 0, `${name} inspection is read-only`);
  }
});

test('content refuses an incompatible route before touching the composer', async () => {
  const h = contentHarness();
  assert.equal((await startContent(h, {job_id: 'job-route', expected_model: 'GPT-6 Thinking', prompt: 'draw'})).accepted, true);
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Native image mode is Create image/);
  assert.match(h.sent[0].error, /Not submitted/);
});

test('plain chat without the native Create image chip refuses before insertion or Send', async () => {
  const h = contentHarness({newUi: true, imageMode: false});
  await startContent(h);
  assert.equal(h.editor.innerText, '');
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Select native Create image/);
});

for (const [name, options] of [
  ['existing draft', {draft: 'keep this'}],
  ['running generation', {busy: true}],
  ['non-empty conversation', {user: true}]
]) {
  test(`content refuses ${name} without clicking send`, async () => {
    const h = contentHarness(options);
    await startContent(h);
    assert.equal(h.clicks, 0);
    assert.match(h.sent[0].error, /fresh empty chat/);
    assert.match(h.sent[0].error, /Not submitted/);
  });
}

test('matching fresh composer inserts once and clicks only native send once', async () => {
  const h = contentHarness();
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.match(h.editor.value, /^Create one image\. Return a generated image, not just a description\./);
  assert.equal(h.sent.length, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
  assert.match(h.sent[0].error, /Timed out/);
});

test('zero-image generation keeps the ordinary prompt and sends without touching a file input', async () => {
  const h = contentHarness();
  await startContent(h, {job_id: 'job-no-images', expected_model: 'Create image', prompt: 'draw a cat', images: []});
  await waitForContentResult(h);
  assert.deepEqual(h.inputEvents, []);
  assert.equal(h.uploadedFiles.length, 0);
  assert.equal(h.sendClicks, 1);
  assert.match(h.editor.value, /^Create one image\. Return a generated image, not just a description\./);
  assert.match(h.sent.at(-1).error, /Submission attempted/);
});

test('one-image upload preserves the actual File bytes, name, MIME type, and event order', async () => {
  const image = imageInput(1, 'reference', [137, 80, 78, 71]);
  const h = contentHarness();
  await startContent(h, {job_id: 'job-one-image', expected_model: 'Create image', prompt: 'use this reference', images: [image]});
  await waitForContentResult(h);

  assert.deepEqual(h.inputEvents, ['input', 'change'], JSON.stringify(h.sent));
  assert.equal(h.uploadedFiles.length, 1, JSON.stringify(h.sent));
  assert.equal(h.uploadedFiles[0].name, image.name);
  assert.equal(h.uploadedFiles[0].type, image.mime);
  assert.deepEqual([...h.uploadedFiles[0].bytes], [...Buffer.from(image.data_base64, 'base64')]);
  assert.equal(h.sendClicks, 1);
  assert.equal(h.sendClickedWhenReady, true);
  assert.match(h.editor.value, /Actual attachments, in upload order:\nImage 1: REFERENCE GUIDANCE — reference 1/);
});

test('inspection separates two user-upload references from one adjacent assistant output', () => {
  const h = contentHarness({user: true, conversationTurns: ['You said:', 'ChatGPT said:'],
    conversationBodies: ['submitted prompt', 'assistant reply'], assistantRoleNodes: 'always',
    userImageSources: ['https://chatgpt.com/reference-1.png', 'https://chatgpt.com/reference-2.png'],
    assistantImageSources: ['https://chatgpt.com/output.png']});
  let result;
  h.receive({type: 'image-inspect'}, {}, value => { result = value; });

  assert.deepEqual(JSON.parse(JSON.stringify(result.result_dom)), {
    assistant_role_nodes: 1, user_headings: 1, assistant_headings: 1, assistant_body_found: true,
    assistant_images: 1, conversation_images: 3, busy: false,
    chat_path: '/c/123e4567-e89b-12d3-a456-426614174000'
  });
});

test('generation collects the last adjacent assistant body, not the two reference images in the user turn', async () => {
  const output = 'https://chatgpt.com/generated-output.png';
  const references = ['https://chatgpt.com/uploaded-reference-1.png', 'https://chatgpt.com/uploaded-reference-2.png'];
  const h = contentHarness({conversationTurnsAfterSend: true, assistantImageSources: [output],
    userImageSources: references});
  const images = [imageInput(1), imageInput(2)];
  await startContent(h, {job_id: 'job-assistant-scope', expected_model: 'Create image', mode: 'create',
    prompt: 'use these references', images});
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.imageBase64);
  assert.ok(receipt, JSON.stringify(h.sent));
  assert.equal(receipt.imageBase64, 'cG5n');
  assert.equal(receipt.imagesBase64, undefined);
  assert.deepEqual(h.fetchedUrls, [output]);
  assert.equal(h.sendClicks, 1);
  assert.deepEqual(h.uploadedFiles.map(file => file.name), images.map(image => image.name));
});

test('generation collects every stable assistant output image', async () => {
  const outputs = ['https://chatgpt.com/generated-output-1.png', 'https://chatgpt.com/generated-output-2.png'];
  const h = contentHarness({assistantRoleNodes: true, assistantImageSources: outputs});
  await startContent(h, {job_id: 'job-two-assistant-outputs', expected_model: 'Create image', prompt: 'draw two panels', images: []});
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.imagesBase64);
  assert.ok(receipt, JSON.stringify(h.sent));
  assert.equal(receipt.imageBase64, undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(receipt.imagesBase64)), ['cG5n', 'cG5n']);
  assert.deepEqual(h.fetchedUrls, outputs);
  assert.equal(h.fileReaderReads, 2);
  assert.equal(h.sendClicks, 1);
});

test('duplicate assistant image URLs are deduplicated before collection', async () => {
  const output = 'https://chatgpt.com/generated-output.png';
  const h = contentHarness({assistantRoleNodes: true, assistantImageSources: [output, output]});
  await startContent(h, {job_id: 'job-duplicate-output-url', expected_model: 'Create image', prompt: 'draw one image', images: []});
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.imageBase64);
  assert.ok(receipt, JSON.stringify(h.sent));
  assert.equal(receipt.imagesBase64, undefined);
  assert.deepEqual(h.fetchedUrls, [output]);
  assert.equal(h.fileReaderReads, 1);
  assert.equal(h.sendClicks, 1);
});

test('more than four assistant outputs fail closed without downloading or resending', async () => {
  const outputs = Array.from({length: 5}, (_, index) => `https://chatgpt.com/generated-output-${index + 1}.png`);
  const h = contentHarness({assistantRoleNodes: true, assistantImageSources: outputs});
  await startContent(h, {job_id: 'job-too-many-outputs', expected_model: 'Create image', prompt: 'draw many images', images: []});
  await waitForContentResult(h);

  const result = h.sent.at(-1);
  assert.match(result.error, /Submission attempted.*More than four assistant images/);
  assert.equal(result.imageBase64, undefined);
  assert.equal(result.imagesBase64, undefined);
  assert.equal(h.fetchCalls, 0);
  assert.equal(h.sendClicks, 1);
});

test('changed assistant output set is not collected and never triggers another Send', async () => {
  const first = 'https://chatgpt.com/generated-output-1.png';
  const replacement = 'https://chatgpt.com/generated-output-2.png';
  const h = contentHarness({assistantRoleNodes: true,
    assistantImageSequence: [[first], [first], [first], [replacement]]});
  await startContent(h, {job_id: 'job-output-changed', expected_model: 'Create image', prompt: 'draw one image', images: []});
  await waitForContentResult(h);

  const result = h.sent.at(-1);
  assert.match(result.error, /Submission attempted.*Existing result changed during collection/);
  assert.equal(result.imageBase64, undefined);
  assert.equal(result.imagesBase64, undefined);
  assert.equal(h.sendClicks, 1, 'a changed result is not resubmitted');
});

test('upload preflight accepts and clears the exact per-job snapshot filename', async () => {
  const jobId = 'a'.repeat(32);
  const image = imageInput(1);
  image.name = `input-001-${jobId}.png`;
  const h = contentHarness({nativeUploadCards: true, reactClearsInputFiles: true});
  await startContent(h, {job_id: jobId, expected_model: 'Create image', mode: 'create', prompt: 'draw a cat',
    images: [image], preflight_only: true, clear_preflight_uploads: true});
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipt?.preflightUploadsCleared, true);
  assert.deepEqual(h.removedUploadNames, [image.name]);
  assert.deepEqual(h.uploadedFiles, []);
  assert.deepEqual(h.fileInputs[0].files, []);
  assert.deepEqual(h.inputEvents, ['input', 'change']);
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
});

test('ordinary upload rejects a duplicate-name alias accepted only by cleanup inspection', async () => {
  const image = imageInput(1);
  image.name = 'input-001(1).png';
  const h = contentHarness();
  await startContent(h, {job_id: 'job-normal-upload-rejects-alias', expected_model: 'Create image', mode: 'create',
    prompt: 'draw a cat', images: [image], preflight_only: true});
  await waitForContentResult(h);

  assert.match(h.sent.at(-1).error, /Invalid ordered image input/);
  assert.deepEqual(h.inputEvents, []);
  assert.equal(h.removeClicks, 0);
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
});

test('three-image edit uploads source then references in order and waits for all attachments before Send', async () => {
  const images = [
    imageInput(1, 'source', [1, 2, 3]),
    imageInput(2, 'reference', [4, 5, 6, 7]),
    imageInput(3, 'reference', [8, 9, 10, 11, 12])
  ];
  const h = contentHarness({uploadReadyAfterChecks: 6});
  await startContent(h, {job_id: 'job-edit-three', expected_model: 'Create image', mode: 'edit', prompt: 'edit the source', images});
  await waitForContentResult(h);

  assert.deepEqual(h.inputEvents, ['input', 'change'], JSON.stringify(h.sent));
  assert.equal(h.uploadedFiles.length, 3);
  assert.deepEqual(h.uploadedFiles.map(file => [file.name, file.type, [...file.bytes]]), images.map(image => [
    image.name, image.mime, [...Buffer.from(image.data_base64, 'base64')]
  ]));
  assert.ok(h.uploadReadyChecks > 6, 'the delayed native cards must be checked before Send becomes available');
  assert.equal(h.sendClicks, 1);
  assert.equal(h.sendClickedWhenReady, true);
  assert.match(h.editor.value, /Image 1: SOURCE TO EDIT — source 1\nImage 2: REFERENCE GUIDANCE — reference 2\nImage 3: REFERENCE GUIDANCE — reference 3/);
});

test('zero-image create preflight returns one readiness receipt without editing or submitting', async () => {
  const h = contentHarness();
  await startContent(h, {job_id: 'job-preflight-empty-create', expected_model: 'Create image', mode: 'create',
    prompt: 'draw a cat', images: [], preflight_only: true});
  await waitForContentResult(h);

  const receipts = h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipts.length, 1);
  assert.deepEqual(Object.keys(receipts[0]).sort(), ['jobId', 'preflightReady', 'type']);
  assert.equal(h.sent.length, 1);
  assert.equal(h.uploadedFiles.length, 0);
  assert.equal(h.editor.value, 'Create image');
  assert.deepEqual(h.composerEvents, []);
  assert.equal(h.insertTextCalls, 0);
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.clicks, 0);
  assert.equal(h.fetchCalls, 0);
  assert.equal(h.fileReaderReads, 0);
  assert.equal(h.finalDeleteClicks, 0);
});

test('three-image edit preflight waits for source and references, then leaves their native Files attached', async () => {
  const images = [
    imageInput(1, 'source', [21, 22, 23]),
    imageInput(2, 'reference', [31, 32, 33, 34]),
    imageInput(3, 'reference', [41, 42, 43, 44, 45])
  ];
  const h = contentHarness({uploadReadyAfterChecks: 5});
  await startContent(h, {job_id: 'job-preflight-edit-three', expected_model: 'Create image', mode: 'edit',
    prompt: 'edit the source', images, preflight_only: true});
  await waitForContentResult(h);

  const receipts = h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipts.length, 1);
  assert.deepEqual(Object.keys(receipts[0]).sort(), ['jobId', 'preflightReady', 'type']);
  assert.equal(h.sent.length, 1);
  assert.deepEqual(h.inputEvents, ['input', 'change']);
  assert.deepEqual(h.uploadedFiles.map(file => [file.name, file.type, [...file.bytes]]), images.map(image => [
    image.name, image.mime, [...Buffer.from(image.data_base64, 'base64')]
  ]));
  assert.ok(h.uploadReadyChecks > 5, 'preflight waits for all visible attachment cards');
  assert.equal(h.uploadReadyState, true, 'the worker leaves its verified attachments in the composer');
  assert.equal(h.editor.value, 'Create image');
  assert.deepEqual(h.composerEvents, []);
  assert.equal(h.insertTextCalls, 0);
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.clicks, 0);
  assert.equal(h.fetchCalls, 0);
  assert.equal(h.fileReaderReads, 0);
  assert.equal(h.finalDeleteClicks, 0);
});

test('opt-in upload preflight clears zero or one owned image without touching the chat', async t => {
  await t.test('zero-image preflight returns a cleared receipt without clicking Remove', async () => {
    const h = contentHarness();
    await startContent(h, {job_id: 'job-clear-empty', expected_model: 'Create image', mode: 'create',
      prompt: 'draw a cat', images: [], preflight_only: true, clear_preflight_uploads: true});
    await waitForContentResult(h);

    const receipts = h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true);
    assert.equal(receipts.length, 1);
    assert.deepEqual(Object.keys(receipts[0]).sort(), ['jobId', 'preflightReady', 'preflightUploadsCleared', 'type']);
    assert.equal(receipts[0].preflightUploadsCleared, true);
    assert.equal(h.removeClicks, 0);
    assert.equal(h.uploadedFiles.length, 0);
    assert.deepEqual(h.inputEvents, []);
    assert.equal(h.editor.value, 'Create image');
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.fetchCalls, 0);
    assert.equal(h.fileReaderReads, 0);
    assert.equal(h.finalDeleteClicks, 0);
  });

  await t.test('one-image preflight removes only its verified native card', async () => {
    const image = imageInput(1);
    const h = contentHarness();
    await startContent(h, {job_id: 'job-clear-one', expected_model: 'Create image', mode: 'create',
      prompt: 'draw a cat', images: [image], preflight_only: true, clear_preflight_uploads: true});
    await waitForContentResult(h);

    const receipt = h.sent.find(message => message.type === 'image-result' && message.preflightReady === true);
    assert.equal(receipt?.preflightUploadsCleared, true);
    assert.deepEqual(h.removedUploadNames, [image.name]);
    assert.equal(h.uploadedFiles.length, 0);
    assert.deepEqual(h.inputEvents, ['input', 'change'], 'cleanup uses native Remove, not a file input reset');
    assert.equal(h.editor.value, 'Create image');
    assert.deepEqual(h.composerEvents, []);
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.fetchCalls, 0);
    assert.equal(h.fileReaderReads, 0);
    assert.equal(h.finalDeleteClicks, 0);
  });
});

test('opt-in three-image edit preflight removes only its verified files in order', async () => {
  const images = [imageInput(1, 'source'), imageInput(2, 'reference'), imageInput(3, 'reference')];
  const h = contentHarness({uploadReadyAfterChecks: 4});
  await startContent(h, {job_id: 'job-clear-three', expected_model: 'Create image', mode: 'edit',
    prompt: 'edit the source', images, preflight_only: true, clear_preflight_uploads: true});
  await waitForContentResult(h);

  const receipts = h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipts.length, 1);
  assert.equal(receipts[0].preflightUploadsCleared, true);
  assert.deepEqual(h.removedUploadNames, images.map(image => image.name));
  assert.equal(h.uploadedFiles.length, 0);
  assert.deepEqual(h.inputEvents, ['input', 'change']);
  assert.equal(h.editor.value, 'Create image');
  assert.equal(h.composerEvents.length, 0);
  assert.equal(h.insertTextCalls, 0);
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.fetchCalls, 0);
  assert.equal(h.fileReaderReads, 0);
  assert.equal(h.finalDeleteClicks, 0);
});

test('clear preflight waits for delayed native Remove updates before removing the next file', async () => {
  const images = [imageInput(1), imageInput(2)];
  const h = contentHarness({nativeUploadCards: true, reactClearsInputFiles: true, delayedNativeRemovePolls: 2});
  await startContent(h, {job_id: 'job-clear-delayed-native-remove', expected_model: 'Create image', mode: 'create',
    prompt: 'draw a cat', images, preflight_only: true, clear_preflight_uploads: true});
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipt?.preflightUploadsCleared, true);
  assert.deepEqual(h.removedUploadNames, images.map(image => image.name));
  assert.deepEqual(h.uploadedFiles, []);
  assert.deepEqual(h.fileInputs[0].files, [], 'React may clear the FileList independently of its delayed card update');
  assert.deepEqual(h.inputEvents, ['input', 'change']);
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.insertTextCalls, 0);
  assert.equal(h.finalDeleteClicks, 0);
});

test('clear preflight flags are validated before upload while explicit false stays backward-compatible', async t => {
  for (const [name, job] of [
    ['clear outside preflight', {preflight_only: false, clear_preflight_uploads: true}],
    ['non-boolean clear flag', {preflight_only: true, clear_preflight_uploads: 'yes'}]
  ]) await t.test(name, async () => {
    const h = contentHarness();
    await startContent(h, {job_id: `job-invalid-clear-${name}`, expected_model: 'Create image', mode: 'create',
      prompt: 'draw a cat', images: [imageInput(1)], ...job});
    await waitForContentResult(h);
    assert.equal(h.inputEvents.length, 0);
    assert.equal(h.removeClicks, 0);
    assert.equal(h.sendClicks, 0);
    assert.match(h.sent.at(-1).error, /clear_preflight_uploads is valid only/);
  });

  await t.test('false on an ordinary generation leaves normal submission intact', async () => {
    const h = contentHarness();
    await startContent(h, {job_id: 'job-clear-false-generation', expected_model: 'Create image', mode: 'create',
      prompt: 'draw a cat', images: [], clear_preflight_uploads: false});
    await waitForContentResult(h);
    assert.equal(h.sendClicks, 1);
    assert.equal(h.removeClicks, 0);
    assert.match(h.sent.at(-1).error || '', /Submission attempted/);
  });
});

test('clear preflight fails closed if the draft, attachments, Remove control, or readiness changes', async t => {
  const images = [imageInput(1, 'source'), imageInput(2, 'reference'), imageInput(3, 'reference')];
  const cases = [
    ['foreign text before cleanup', {changeDuringUpload: 'text'}, 0, 3],
    ['foreign attachment before cleanup', {uploadOutside: true}, 0, 3],
    ['foreign text between removals', {foreignTextAfterRemoveAt: 1}, 1, 2],
    ['foreign attachment between removals', {foreignAttachmentAfterRemoveAt: 1}, 1, 3],
    ['Remove control disappears between removals', {removeControlUnavailableAfter: 1}, 1, 2],
    ['native upload progress persists after Remove', {removeProgressAfterClick: true}, 1, 2]
  ];
  for (const [name, options, expectedRemovals, expectedFiles] of cases) await t.test(name, async () => {
    const h = contentHarness(options);
    await startContent(h, {job_id: `job-clear-guard-${name}`, expected_model: 'Create image', mode: 'edit',
      prompt: 'edit the source', images, preflight_only: true, clear_preflight_uploads: true});
    await waitForContentResult(h);

    assert.equal(h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true).length, 0);
    assert.equal(h.sent.filter(message => message.type === 'image-result').length, 1);
    assert.match(h.sent.at(-1).error, /Not submitted/);
    assert.equal(h.removeClicks, expectedRemovals);
    assert.equal(h.uploadedFiles.length, expectedFiles);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.fetchCalls, 0);
    assert.equal(h.fileReaderReads, 0);
    assert.equal(h.finalDeleteClicks, 0);
  });
});

test('clear preflight rechecks draft, foreign attachments, and chat path during delayed Remove waits', async t => {
  const images = [imageInput(1, 'source'), imageInput(2, 'reference'), imageInput(3, 'reference')];
  const matchingPrompt = 'Edit the attached source image(s) following the instructions. Return one edited image.\n' +
    'Actual attachments, in upload order:\nImage 1: SOURCE TO EDIT — source 1\n' +
    'Image 2: REFERENCE GUIDANCE — reference 2\nImage 3: REFERENCE GUIDANCE — reference 3\n\nedit the source';
  const cases = [
    ['foreign composer text', {foreignTextAfterRemoveWaits: 1}, /Preserve composer text/],
    ['matching job draft', {matchingDraftAfterRemoveWaits: matchingPrompt}, /Preserve composer text/],
    ['foreign attachment', {foreignAttachmentAfterRemoveWaits: 1}, /Unexpected attachment controls/],
    ['chat path change', {pathChangeAfterRemoveWaits: 1}, /Composer changed while removing/]
  ];
  for (const [name, change, expectedError] of cases) await t.test(name, async () => {
    const h = contentHarness({nativeUploadCards: true, reactClearsInputFiles: true, delayedNativeRemovePolls: 3, ...change});
    await startContent(h, {job_id: `job-clear-delayed-guard-${name}`, expected_model: 'Create image', mode: 'edit',
      prompt: 'edit the source', images, preflight_only: true, clear_preflight_uploads: true});
    await waitForContentResult(h);

    assert.equal(h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true).length, 0);
    assert.equal(h.removeClicks, 1, 'the first Remove is the only action before the pending-state guard');
    assert.equal(h.uploadedFiles.length, name === 'foreign attachment' ? images.length + 1 : images.length,
      'the still-visible attachment cards are preserved while React has not applied removal');
    assert.match(h.sent.at(-1).error, expectedError);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.finalDeleteClicks, 0);
  });
});

test('clear preflight refuses even an exact matching job draft before or between removals', async t => {
  await t.test('zero-image preflight preserves an exact matching prompt and sends no cleared receipt', async () => {
    const prompt = 'Create one image. Return a generated image, not just a description.\n\ndraw a cat';
    const h = contentHarness({draft: prompt});
    await startContent(h, {job_id: 'job-clear-zero-matching-draft', expected_model: 'Create image', mode: 'create',
      prompt: 'draw a cat', images: [], preflight_only: true, clear_preflight_uploads: true});
    await waitForContentResult(h);

    assert.equal(h.sent.filter(message => message.preflightReady === true).length, 0);
    assert.match(h.sent.at(-1).error, /Preserve composer text/);
    assert.equal(h.editor.value, `Create image ${prompt}`);
    assert.equal(h.removeClicks, 0);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
  });

  await t.test('matching original job prompt typed between removals stops further cleanup', async () => {
    const images = [imageInput(1, 'source'), imageInput(2, 'reference'), imageInput(3, 'reference')];
    const prompt = 'Edit the attached source image(s) following the instructions. Return one edited image.\n' +
      'Actual attachments, in upload order:\nImage 1: SOURCE TO EDIT — source 1\n' +
      'Image 2: REFERENCE GUIDANCE — reference 2\nImage 3: REFERENCE GUIDANCE — reference 3\n\nedit the source';
    const h = contentHarness({matchingDraftAfterRemoveAt: prompt});
    await startContent(h, {job_id: 'job-clear-between-matching-draft', expected_model: 'Create image', mode: 'edit',
      prompt: 'edit the source', images, preflight_only: true, clear_preflight_uploads: true});
    await waitForContentResult(h);

    assert.equal(h.sent.filter(message => message.preflightReady === true).length, 0);
    assert.match(h.sent.at(-1).error, /Preserve composer text/);
    assert.equal(h.removeClicks, 1);
    assert.deepEqual(h.uploadedFiles.map(file => file.name), images.slice(1).map(image => image.name));
    assert.equal(h.editor.value, `Create image ${prompt}`);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
  });
});

test('failed preflight uploads never click or look up Send and never return readiness', async t => {
  const cases = [
    ['partial upload', {uploadPartial: true}],
    ['native upload error', {uploadError: true}],
    ['missing file input', {uploadInput: false}]
  ];
  for (const [name, options] of cases) await t.test(name, async () => {
    const h = contentHarness(options);
    await startContent(h, {job_id: `job-preflight-failed-${name}`, expected_model: 'Create image', mode: 'create',
      prompt: 'draw a cat', images: [imageInput(1), imageInput(2), imageInput(3)], preflight_only: true});
    await waitForContentResult(h);

    assert.equal(h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true).length, 0);
    assert.equal(h.sent.length, 1);
    assert.match(h.sent[0].error, /Not submitted/);
    assert.equal(h.editor.value, 'Create image');
    assert.deepEqual(h.composerEvents, []);
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.clicks, 0);
    assert.equal(h.fetchCalls, 0);
    assert.equal(h.fileReaderReads, 0);
  });
});

test('edit mode requires a source image and rejects references-only input before upload', async () => {
  const h = contentHarness();
  await startContent(h, {job_id: 'job-edit-no-source', expected_model: 'Create image', mode: 'edit', prompt: 'edit this',
    images: [imageInput(1, 'reference')]});
  await waitForContentResult(h);

  assert.deepEqual(h.inputEvents, []);
  assert.equal(h.sendClicks, 0);
  assert.match(h.sent.at(-1).error, /Not submitted.*Invalid create\/edit image roles/);
});

test('upload preflight keeps a sole compatible mixed-purpose input', async () => {
  const images = [imageInput(1), imageInput(2), imageInput(3)];
  const h = contentHarness({uploadInputSpecs: [{accept: 'image/*,application/pdf', multiple: true}]});
  await startContent(h, {job_id: 'job-preflight-one-compatible-input', expected_model: 'Create image',
    prompt: 'draw', images, preflight_only: true});
  await waitForContentResult(h);

  assert.ok(h.sent.find(message => message.type === 'image-result' && message.preflightReady === true));
  assert.deepEqual(h.fileInputs.map(input => input.files.length), [images.length]);
  assert.deepEqual(h.uploadedFiles.map(file => file.name), images.map(image => image.name));
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.fetchCalls, 0);
  assert.equal(h.fileReaderReads, 0);
});

test('upload preflight prefers one image-only multi-file input over a general file picker', async () => {
  const images = [imageInput(1), imageInput(2), imageInput(3)];
  const h = contentHarness({uploadInputSpecs: [
    {accept: 'image/*,application/pdf', multiple: true},
    {accept: '.png,.jpg,.webp', multiple: true}
  ]});
  await startContent(h, {job_id: 'job-preflight-dedicated-image-input', expected_model: 'Create image',
    prompt: 'draw', images, preflight_only: true});
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.preflightReady === true);
  assert.ok(receipt, 'the unambiguous image-only input should be selected');
  assert.deepEqual(h.fileInputs.map(input => input.files.length), [0, images.length],
    'the general image-and-PDF input stays untouched');
  assert.deepEqual(h.uploadedFiles.map(file => file.name), images.map(image => image.name),
    'the dedicated input receives all images in their declared order');
  assert.deepEqual(h.inputEvents, ['input', 'change']);
  assert.equal(h.insertTextCalls, 0);
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.fetchCalls, 0);
  assert.equal(h.fileReaderReads, 0);
});

test('upload preflight rejects ambiguous or mixed-token image inputs before any upload', async t => {
  const images = [imageInput(1), imageInput(2), imageInput(3)];
  const cases = [
    ['two image-only inputs', {uploadInputSpecs: [
      {accept: 'image/*', multiple: true}, {accept: '.png,.jpg,.webp', multiple: true}
    ]}, 'compatible=2, image_only=2'],
    ['mixed image and unknown MIME tokens', {uploadInputSpecs: [
      {accept: 'image/*,application/pdf', multiple: true},
      {accept: 'image/png,application/x-unknown', multiple: true}
    ]}, 'compatible=2, image_only=0']
  ];
  for (const [name, options, counts] of cases) await t.test(name, async () => {
    const h = contentHarness(options);
    await startContent(h, {job_id: `job-preflight-${name}`, expected_model: 'Create image', prompt: 'draw',
      images, preflight_only: true});
    await waitForContentResult(h);
    assert.deepEqual(h.inputEvents, []);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.fetchCalls, 0);
    assert.equal(h.fileReaderReads, 0);
    assert.equal(h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true).length, 0);
    assert.match(h.sent.at(-1).error, new RegExp(`Native image file input missing, ambiguous or incompatible; ${counts}`));
    assert.doesNotMatch(h.sent.at(-1).error, /image\/\*|application\/|unknown|input-\d/,
      'the error reports counts only, not accept tokens or file details');
  });
});

test('upload preflight rejects missing, outside-form, disabled, incompatible, or non-multiple inputs', async t => {
  const cases = [
    ['missing input', {uploadInput: false}, [imageInput(1)], /Native image file input missing, ambiguous or incompatible/],
    ['only input is outside the form', {uploadInput: false, outsideUploadInput: {accept: 'image/png', multiple: true}},
      [imageInput(1)], /Native image file input missing, ambiguous or incompatible/],
    ['blank accept is not an upload fallback', {uploadAccept: ''}, [imageInput(1)],
      /Native image file input missing, ambiguous or incompatible/],
    ['missing editor form', {formAvailable: false}, [imageInput(1)], /Native upload composer form unavailable/],
    ['disabled input', {uploadInputSpecs: [{accept: 'image/png', multiple: true, disabled: true}]},
      [imageInput(1)], /Native image file input missing, ambiguous or incompatible/],
    ['wrong accepted MIME', {uploadAccept: 'image/jpeg'}, [imageInput(1)], /Native image file input missing, ambiguous or incompatible/],
    ['multi-image input without multiple', {uploadMultiple: false},
      [imageInput(1), imageInput(2), imageInput(3)], /Native image file input missing, ambiguous or incompatible/]
  ];
  for (const [name, options, images, expectedError] of cases) await t.test(name, async () => {
    const h = contentHarness(options);
    await startContent(h, {job_id: `job-preflight-${name}`, expected_model: 'Create image', prompt: 'draw',
      images, preflight_only: true});
    await waitForContentResult(h);
    assert.deepEqual(h.inputEvents, []);
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.fetchCalls, 0);
    assert.equal(h.fileReaderReads, 0);
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true).length, 0);
    assert.match(h.sent.at(-1).error, new RegExp(`Not submitted.*${expectedError.source}`));
  });
});

test('native attachment cards without test IDs block ready status and clear through their matching Remove buttons', async () => {
  const h = contentHarness({nativeUploadCards: true, nativeAttachmentNames: ['input-001.png', 'input-002.png']});
  let inspection;
  h.receive({type: 'image-inspect'}, {}, value => { inspection = value; });

  assert.match(inspection.error, /Remove existing attachments/);
  assert.equal(inspection.idle, false);
  assert.equal(inspection.upload_dom.attachment_cards, 2);
  assert.equal(h.removeClicks, 0, 'inspection never removes existing native attachments');

  const images = [imageInput(1), imageInput(2)];
  const cleared = contentHarness({nativeUploadCards: true, reactClearsInputFiles: true});
  await startContent(cleared, {job_id: 'job-native-card-preflight-clear', expected_model: 'Create image',
    mode: 'create', prompt: 'check ordered references', images, preflight_only: true, clear_preflight_uploads: true});
  await waitForContentResult(cleared);

  const receipt = cleared.sent.find(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipt?.preflightUploadsCleared, true);
  assert.deepEqual(cleared.fileInputs[0].files, [], 'the page may clear input.files after React accepts the Files');
  assert.deepEqual(cleared.removedUploadNames, images.map(image => image.name));
  assert.deepEqual(cleared.uploadedFiles, []);
  assert.deepEqual(cleared.inputEvents, ['input', 'change']);
  assert.equal(cleared.sendQueries, 0);
  assert.equal(cleared.sendClicks, 0);
  assert.equal(cleared.insertTextCalls, 0);
  assert.equal(cleared.fetchCalls, 0);
  assert.equal(cleared.fileReaderReads, 0);

  let finalInspection;
  cleared.receive({type: 'image-inspect'}, {}, value => { finalInspection = value; });
  assert.equal(finalInspection.fresh, true);
  assert.equal(finalInspection.idle, true);
  assert.equal(finalInspection.upload_dom.attachment_cards, 0);
});

test('cleanup-only preflight removes matching inspected native cards without uploading or sending', async () => {
  const sourceImages = [imageInput(1), imageInput(2)];
  const images = sourceImages.map(({data_base64, ...metadata}) => metadata);
  const h = contentHarness({nativeUploadCards: true, nativeAttachmentNames: images.map(image => image.name), chatPath: '/'});
  await startContent(h, {job_id: 'job-native-cleanup-only', expected_model: 'Create image', mode: 'create',
    prompt: 'validate already attached references', images, preflight_only: true, clear_preflight_uploads: true,
    preflight_cleanup_only: true});
  await waitForContentResult(h);

  const receipts = h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipts.length, 1);
  assert.equal(receipts[0].preflightUploadsCleared, true);
  assert.deepEqual(h.removedUploadNames, images.map(image => image.name));
  assert.deepEqual(h.uploadedFiles, []);
  assert.deepEqual(h.fileInputs[0].files, []);
  assert.deepEqual(h.inputEvents, [], 'cleanup-only never dispatches input/change');
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.insertTextCalls, 0);
  assert.equal(h.fetchCalls, 0);
  assert.equal(h.fileReaderReads, 0);
  assert.equal(h.sent.some(message => message.type === 'image-result' && message.imageBase64), false);
});

test('cleanup-only accepts exact legacy ChatGPT duplicate-name aliases and removes both without Send', async () => {
  const sourceImages = [imageInput(1), imageInput(2)];
  const names = ['input-001(1).png', 'input-002(1).png'];
  const images = sourceImages.map(({data_base64, ...metadata}, index) => ({...metadata, name: names[index]}));
  const h = contentHarness({nativeUploadCards: true, nativeAttachmentNames: names, chatPath: '/'});
  await startContent(h, {job_id: 'job-native-cleanup-legacy-aliases', expected_model: 'Create image', mode: 'create',
    prompt: 'validate already attached references', images, preflight_only: true, clear_preflight_uploads: true,
    preflight_cleanup_only: true});
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipt?.preflightUploadsCleared, true);
  assert.deepEqual(h.removedUploadNames, names);
  assert.deepEqual(h.uploadedFiles, []);
  assert.deepEqual(h.inputEvents, [], 'legacy aliases are inspected and removed, never re-uploaded');
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.insertTextCalls, 0);
  assert.equal(h.sent.some(message => message.type === 'image-result' && message.imageBase64), false);
});

test('cleanup-only preflight refuses changed or mismatched state before clicking Remove', async t => {
  const sourceImages = [imageInput(1), imageInput(2)];
  const metadata = sourceImages.map(({data_base64, ...image}) => image);
  const duplicateImage = {...metadata[0], order: 2};
  const cases = [
    ['changed composer text', {draft: 'changed draft'}, {}, /Inspected preflight draft changed/],
    ['changed chat path', {chatPath: '/c/123e4567-e89b-12d3-a456-426614174000'}, {}, /Inspected preflight draft changed/],
    ['temporary chat', {temporaryChat: true}, {}, /Inspected preflight draft changed/],
    ['existing turns', {user: true}, {}, /Inspected preflight draft changed/],
    ['busy chat', {busy: true}, {}, /Inspected preflight draft changed/],
    ['wrong image order', {}, {images: [metadata[1], metadata[0]]}, /Inspected preflight draft changed/],
    ['missing existing image', {nativeAttachmentNames: ['input-001.png']}, {}, /do not exactly match/],
    ['unmarked suffix recovery', {nativeAttachmentNames: ['input-002.png']}, {}, /do not exactly match/],
    ['non-suffix remaining subset', {nativeAttachmentNames: ['input-001.png']}, {}, /do not exactly match/],
    ['foreign existing image', {nativeAttachmentNames: ['input-001.png', 'input-002.png', 'foreign.png']}, {}, /do not exactly match/],
    ['duplicate existing image card', {nativeAttachmentNames: ['input-001.png', 'input-001.png']}, {}, /do not exactly match/],
    ['duplicate requested image name', {}, {images: [metadata[0], duplicateImage]}, /Inspected preflight draft changed/],
    ['byte payload included', {}, {images: sourceImages}, /Inspected preflight draft changed/],
    ['clear flag false', {}, {clear_preflight_uploads: false}, /Invalid cleanup-only preflight/],
    ['preflight flag false', {}, {preflight_only: false}, /clear_preflight_uploads is valid only/]
  ];

  for (const [name, harnessOptions, jobOptions, expectedError] of cases) await t.test(name, async () => {
    const h = contentHarness({nativeUploadCards: true, chatPath: '/', ...harnessOptions});
    await startContent(h, {job_id: `job-native-cleanup-refusal-${name}`, expected_model: 'Create image', mode: 'create',
      prompt: 'validate already attached references', images: metadata, preflight_only: true,
      clear_preflight_uploads: true, preflight_cleanup_only: true, ...jobOptions});
    await waitForContentResult(h);

    assert.equal(h.removeClicks, 0, 'refusal preserves all existing attachment cards');
    assert.deepEqual(h.removedUploadNames, []);
    assert.deepEqual(h.inputEvents, [], 'refusal never dispatches input/change');
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.fetchCalls, 0);
    assert.equal(h.fileReaderReads, 0);
    assert.equal(h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true).length, 0);
    assert.match(h.sent.at(-1).error, expectedError);
  });
});

test('cleanup-only preflight recovery binds and clears only the exact remaining ordered suffix', async () => {
  const sourceImages = [imageInput(1), imageInput(2), imageInput(3)];
  const images = sourceImages.map(({data_base64, ...metadata}) => metadata);
  const suffix = images.slice(-1);
  const h = contentHarness({nativeUploadCards: true, nativeAttachmentNames: suffix.map(image => image.name), chatPath: '/'});
  await startContent(h, {job_id: 'job-native-cleanup-suffix-recovery', expected_model: 'Create image', mode: 'create',
    prompt: 'validate already attached references', images, preflight_only: true, clear_preflight_uploads: true,
    preflight_cleanup_only: true, preflight_cleanup_resumed: true});
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.preflightReady === true);
  assert.equal(receipt?.preflightUploadsCleared, true);
  assert.deepEqual(h.removedUploadNames, suffix.map(image => image.name));
  assert.deepEqual(h.uploadedFiles, []);
  assert.deepEqual(h.inputEvents, [], 'cleanup-only recovery never re-uploads files');
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.insertTextCalls, 0);
});

test('unpaired native thumbnail blocks inspection and cleanup without a Remove control', async () => {
  const sourceImages = [imageInput(1), imageInput(2)];
  const images = sourceImages.map(({data_base64, ...image}) => image);
  const h = contentHarness({nativeUploadCards: true, nativeAttachmentNames: images.map(image => image.name),
    nativeUnpairedThumbnail: true, chatPath: '/'});
  let inspection;
  h.receive({type: 'image-inspect'}, {}, value => { inspection = value; });

  assert.match(inspection.error, /Remove existing attachments/);
  assert.equal(inspection.idle, false);
  assert.equal(h.removeClicks, 0);

  await startContent(h, {job_id: 'job-unpaired-native-thumbnail', expected_model: 'Create image', mode: 'create',
    prompt: 'validate already attached references', images, preflight_only: true, clear_preflight_uploads: true,
    preflight_cleanup_only: true});
  await waitForContentResult(h);

  assert.equal(h.removeClicks, 0);
  assert.deepEqual(h.removedUploadNames, []);
  assert.deepEqual(h.inputEvents, []);
  assert.equal(h.sendQueries, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.insertTextCalls, 0);
  assert.equal(h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true).length, 0);
  assert.match(h.sent.at(-1).error, /Unrecognized attachment thumbnail/);
});

test('native no-test-ID preflight refuses foreign, unverified, missing-Remove, or ambiguous attachments', async t => {
  const images = [imageInput(1), imageInput(2)];
  const cases = [
    ['foreign attachment with a duplicate name', {nativeForeignOnUpload: 'input-001.png'}, /Unexpected attachment controls/],
    ['foreign attachment with a different name', {nativeForeignOnUpload: 'foreign.png'}, /Unexpected attachment controls/],
    ['missing thumbnail', {nativeNoThumbnail: true}, /Native uploads not verified ready/],
    ['missing visible Remove', {uploadMissingRemove: true}, /Native uploads not verified ready/],
    ['ambiguous card with multiple Remove controls', {nativeAmbiguousContainer: true}, /Unrecognized attachment thumbnail/]
  ];
  for (const [name, options, expectedError] of cases) await t.test(name, async () => {
    const h = contentHarness({nativeUploadCards: true, reactClearsInputFiles: true, ...options});
    await startContent(h, {job_id: `job-native-unsafe-${name}`, expected_model: 'Create image', mode: 'create',
      prompt: 'check ordered references', images, preflight_only: true, clear_preflight_uploads: true});
    await waitForContentResult(h);

    assert.deepEqual(h.fileInputs[0].files, [], 'React has cleared the native FileList');
    assert.deepEqual(h.removedUploadNames, [], 'unverified or foreign cards are never removed');
    assert.equal(h.sent.filter(message => message.type === 'image-result' && message.preflightReady === true).length, 0);
    assert.match(h.sent.at(-1).error, new RegExp(expectedError.source));
    assert.equal(h.sendQueries, 0);
    assert.equal(h.sendClicks, 0);
    assert.equal(h.insertTextCalls, 0);
    assert.equal(h.fetchCalls, 0);
    assert.equal(h.fileReaderReads, 0);
  });
});

test('partial, reordered, errored, or out-of-scope native uploads never reach Send', async t => {
  const cases = [
    ['partial upload', {uploadPartial: true}, /Native uploads not verified ready/],
    ['reordered upload', {uploadReorder: true}, /Native uploads not verified ready/],
    ['native upload error', {uploadError: true}, /Native attachment error/],
    ['attachment outside composer', {uploadOutside: true}, /Unexpected attachments outside this job's composer/],
    ['missing remove control', {uploadMissingRemove: true}, /Native uploads not verified ready/],
    ['missing loaded thumbnail', {uploadMissingThumbnail: true}, /Native uploads not verified ready/],
    ['upload remains pending', {uploadNeverReady: true}, /Native uploads not verified ready/]
  ];
  for (const [name, options, expected] of cases) await t.test(name, async () => {
    const h = contentHarness(options);
    await startContent(h, {job_id: `job-upload-failure-${name}`, expected_model: 'Create image', prompt: 'draw',
      images: [imageInput(1), imageInput(2), imageInput(3)]});
    await waitForContentResult(h);
    assert.deepEqual(h.inputEvents, ['input', 'change']);
    assert.equal(h.sendClicks, 0);
    assert.match(h.sent.at(-1).error, expected);
  });
});

test('composer changes while uploads are pending stop before text insertion or Send', async () => {
  const h = contentHarness({uploadReadyAfterChecks: 4, changeDuringUpload: 'text'});
  await startContent(h, {job_id: 'job-upload-composer-change', expected_model: 'Create image', prompt: 'draw', images: [imageInput(1)]});
  await waitForContentResult(h);

  assert.deepEqual(h.inputEvents, ['input', 'change']);
  assert.equal(h.sendClicks, 0);
  assert.match(h.sent.at(-1).error, /Not submitted.*fresh empty chat/);
  assert.match(h.editor.value, /changed during upload/);
});

test('attachments removed after readiness but before Send fail closed', async () => {
  const h = contentHarness({uploadRemovedBeforeSend: true});
  await startContent(h, {job_id: 'job-removed-before-send', expected_model: 'Create image', prompt: 'draw', images: [imageInput(1)]});
  await waitForContentResult(h);

  assert.deepEqual(h.inputEvents, ['input', 'change']);
  assert.equal(h.sendClicks, 0, 'Send must not be clicked after the native attachment disappears');
  assert.match(h.sent.at(-1).error, /Not submitted.*(?:attachment|upload)/i);
});

test('base64 bytes that do not match the declared SHA-256 are rejected before upload or Send', async () => {
  const image = imageInput(1);
  image.data_base64 = Buffer.from([99, 98, 97, 96]).toString('base64');
  const h = contentHarness();
  await startContent(h, {job_id: 'job-corrupt-image', expected_model: 'Create image', prompt: 'draw', images: [image]});
  await waitForContentResult(h);

  assert.deepEqual(h.inputEvents, []);
  assert.equal(h.sendClicks, 0);
  assert.match(h.sent.at(-1).error, /Not submitted.*Input byte integrity check failed/);
});

test('current ChatGPT contenteditable UI inserts exact prompt and clicks native send once', async () => {
  const expectedModel = 'Create image';
  const h = contentHarness({newUi: true});
  assert.equal((await startContent(h, {job_id: 'job-2', expected_model: expectedModel, prompt: 'draw a cat'})).accepted, true);
  assert.equal(h.clicks, 1);
  assert.match(h.editor.innerText, /^Create imageCreate one image\. Return a generated image, not just a description\./);
  assert.equal(h.sent.length, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
  assert.match(h.sent[0].error, /Timed out/);
});

test('matching unsent prompt is reused without duplicate insertion before Send', async () => {
  const prompt = 'draw a cat';
  const draft = 'Create one image. Return a generated image, not just a description.\n\n' + prompt;
  const h = contentHarness({newUi: true, draft});
  await startContent(h, {job_id: 'job-reuse', expected_model: 'Create image', prompt});
  assert.equal(h.clicks, 1);
  assert.equal(h.editor.innerText, `Create image ${draft}`);
  assert.equal(h.sent.length, 1);
});

test('native Send lookup waits for a delayed button mount', async () => {
  const h = contentHarness({sendDelayQueries: 3});
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
});

test('native Send lookup waits until the mounted button is enabled', async () => {
  const h = contentHarness({sendDisabledQueries: 4});
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
});

test('native Send lookup skips a hidden matching button and clicks the visible one', async () => {
  const h = contentHarness({hiddenFirstSend: true});
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
});

test('native Send that never becomes ready is not clicked', async () => {
  const h = contentHarness({sendDisabledQueries: 1000});
  await startContent(h);
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Native send button unavailable/);
});

test('draft, lost image chip, busy state, or changed text while waiting for Send fails closed', async () => {
  for (const [name, changeDuringSend, error] of [
    ['unrelated draft', null, /fresh empty chat/],
    ['lost image chip', 'chip', /Native send button unavailable/],
    ['busy state', 'busy', /fresh empty chat/],
    ['changed text', 'text', /Composer text changed/]
  ]) {
    const options = name === 'unrelated draft' ? {draft: 'keep this'} : {changeDuringSend};
    const h = contentHarness({...options, sendDelayQueries: name === 'unrelated draft' ? 0 : 1});
    await startContent(h);
    assert.equal(h.clicks, 0, `${name} must not click Send`);
    assert.match(h.sent[0].error, error, `${name} must fail closed`);
    assert.match(h.sent[0].error, /Not submitted/);
  }
});

test('losing the native Create image chip during insertion fails closed before Send', async () => {
  const h = contentHarness({newUi: true, loseImageChipOnInsert: true});
  await startContent(h);
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Native send button unavailable/);
});

test('contenteditable paragraph newline inflation does not reject the correct prompt', async () => {
  const expectedModel = 'Create image';
  const h = contentHarness({newUi: true, inflateWhitespace: true});
  await startContent(h, {job_id: 'job-3', expected_model: expectedModel, prompt: 'draw a cat'});
  assert.match(h.editor.innerText, /Create one image\. Return a generated image.*\n{5}draw a cat/);
  assert.equal(h.clicks, 1);
  assert.match(h.sent[0].error, /Submission attempted/);
});

test('whitespace normalization does not accept changed prompt words', async () => {
  const expectedModel = 'Create image';
  const h = contentHarness({newUi: true, inflateWhitespace: true, corruptInsertion: true});
  await startContent(h, {job_id: 'job-4', expected_model: expectedModel, prompt: 'draw a cat'});
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Not submitted.*Composer text changed/);
});

test('collection-only accepts one existing conversation and never inserts or clicks Send', async () => {
  const originalPrompt = 'Create image Create one image. Return a generated image, not just a description.\n\ndraw a cat';
  const h = contentHarness({newUi: true, imageReady: true,
    conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: [originalPrompt]});
  const accepted = await startCollect(h);
  assert.ok(accepted?.accepted);
  await waitForContentResult(h);
  const receipt = h.sent.find(message => message.type === 'image-result' && message.imageBase64);
  assert.ok(receipt, JSON.stringify(h.sent));
  assert.equal(receipt.promptBinding, undefined, 'legacy collect jobs do not send new diagnostics');
  assert.equal(h.editor.innerText, 'Create image');
  assert.equal(h.clicks, 0);
});

test('submitted-job recovery collects only from the exact inspected chat and preserves it', async () => {
  const chatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const originalImages = [imageInput(1), imageInput(2)].map(({data_base64, ...metadata}) => metadata);
  const originalPrompt = 'Create image Create one image. Return a generated image, not just a description.\n' +
    'Actual attachments, in upload order:\nImage 1: REFERENCE GUIDANCE — reference 1\n' +
    'Image 2: REFERENCE GUIDANCE — reference 2\n\ndraw a cat';
  const h = contentHarness({newUi: true, chatPath, imageReady: true,
    conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: [originalPrompt]});
  const accepted = await startCollect(h, 'Create image', 'draw a cat', {
    collect_only: true, preserve_chat: true, recovery_chat_path: chatPath, images: originalImages
  });
  assert.ok(accepted?.accepted);
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.imageBase64);
  assert.ok(receipt, JSON.stringify(h.sent));
  assert.equal(receipt.chatPath, chatPath);
  assert.equal(receipt.imageBase64, 'cG5n');
  assert.deepEqual(JSON.parse(JSON.stringify(receipt.promptBinding)), {
    root_match: true, exact_matching_descendant_count: 0,
    expected_chars: receipt.promptBinding.expected_chars,
    observed_chars: receipt.promptBinding.expected_chars
  });
  assert.equal(h.fetchCalls, 1);
  assert.deepEqual(h.inputEvents, [], 'recovery must not re-upload original references');
  assert.equal(h.sendClicks, 0);
  assert.equal(h.clicks, 0);
  assert.equal(h.sent.some(message => message.type === 'image-delete-prompt'), false);
});

test('submitted-job recovery accepts an exact visible prompt child inside a labelled user-message wrapper', async () => {
  const chatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const originalImages = [imageInput(1), imageInput(2)].map(({data_base64, ...metadata}) => metadata);
  const expectedPrompt = 'Create one image. Return a generated image, not just a description.\n' +
    'Actual attachments, in upload order:\nImage 1: REFERENCE GUIDANCE — reference 1\n' +
    'Image 2: REFERENCE GUIDANCE — reference 2\n\ndraw a cat';
  const wrappedBody = `Create image\nSent in image mode\n${expectedPrompt}\nCopy · Edit`;
  const h = contentHarness({newUi: true, chatPath, imageReady: true,
    conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: [wrappedBody],
    userPromptDescendants: [{innerText: expectedPrompt}]});
  const accepted = await startCollect(h, 'Create image', 'draw a cat', {
    collect_only: true, preserve_chat: true, recovery_chat_path: chatPath, images: originalImages
  });
  assert.ok(accepted?.accepted);
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.imageBase64);
  assert.ok(receipt, JSON.stringify(h.sent));
  assert.equal(receipt.chatPath, chatPath);
  assert.equal(receipt.promptBinding.root_match, false);
  assert.equal(receipt.promptBinding.exact_matching_descendant_count, 1);
  assert.equal(receipt.promptBinding.expected_chars, expectedPrompt.replace(/\s+/g, ' ').trim().length);
  assert.equal(receipt.promptBinding.observed_chars, wrappedBody.replace('Create image', ' ').replace(/\s+/g, ' ').trim().length);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.inputEvents.length, 0);
});

test('submitted-job recovery strips exactly one native image chip prefix from the rendered prompt paragraph', async () => {
  const chatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const originalImages = [imageInput(1), imageInput(2)].map(({data_base64, ...metadata}) => metadata);
  const expectedPrompt = 'Create one image. Return a generated image, not just a description.\n' +
    'Actual attachments, in upload order:\nImage 1: REFERENCE GUIDANCE — reference 1\n' +
    'Image 2: REFERENCE GUIDANCE — reference 2\n\ndraw a cat';
  const wrapperDelta = 'abcdefghijk';
  const paragraphText = `Create image ${expectedPrompt}`;
  const outerBody = `Create image ${wrapperDelta} ${expectedPrompt}`;
  const expectedChars = expectedPrompt.replace(/\s+/g, ' ').trim().length;
  assert.equal(outerBody.replace(/\s+/g, ' ').trim().length, expectedChars + 25);
  assert.equal(outerBody.replace('Create image', ' ').replace(/\s+/g, ' ').trim().length, expectedChars + 12);
  const h = contentHarness({newUi: true, promptLinkBadge: true, chatPath, imageReady: true,
    conversationTurns: ['You said:', 'ChatGPT said:'],
    conversationBodies: [outerBody, 'assistant reply'],
    userPromptDescendants: [
      {innerText: paragraphText, tagName: 'P', parentTag: 'DIV', chipChildIndex: 1},
      {innerText: 'Create image', tagName: 'SPAN', parentTag: 'P', promptLink: true, chipChildIndex: 2},
      {innerText: 'Create image', tagName: 'SPAN', parentTag: 'SPAN'}
    ]});
  const accepted = await startCollect(h, 'Create image', 'draw a cat', {
    collect_only: true, output_binding_revision: 2, preserve_chat: true,
    recovery_chat_path: chatPath, images: originalImages
  });
  assert.ok(accepted?.accepted);
  await waitForContentResult(h);

  const receipt = h.sent.find(message => message.type === 'image-result' && message.imageBase64);
  assert.ok(receipt, JSON.stringify(h.sent));
  assert.equal(receipt.chatPath, chatPath);
  assert.equal(receipt.promptBinding.root_match, false, 'outer wrapper keeps its 12-character delta');
  assert.equal(receipt.promptBinding.exact_matching_descendant_count, 1,
    'the full rendered P matches only after removing its single native chip prefix');
  assert.equal(receipt.promptBinding.expected_chars, expectedChars);
  assert.equal(receipt.promptBinding.observed_chars, expectedChars + 12);
  assert.equal(receipt.promptBinding.matcher_revision, 2);
  assert.equal(h.fetchCalls, 1);
  assert.deepEqual(h.inputEvents, [], 'recovery must not re-upload original references');
  assert.equal(h.sendClicks, 0);
  assert.equal(h.clicks, 0);
});

test('submitted-job recovery rejects malformed rendered-chip matches before reading images', async () => {
  const chatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const originalImages = [imageInput(1), imageInput(2)].map(({data_base64, ...metadata}) => metadata);
  const expectedPrompt = 'Create one image. Return a generated image, not just a description.\n' +
    'Actual attachments, in upload order:\nImage 1: REFERENCE GUIDANCE — reference 1\n' +
    'Image 2: REFERENCE GUIDANCE — reference 2\n\ndraw a cat';
  const outerBody = `Create image abcdefghijk ${expectedPrompt}`;
  const validRenderedPrompt = `Create image ${expectedPrompt}`;
  const cases = [
    ['duplicate chips', [
      {innerText: validRenderedPrompt, tagName: 'P', chipChildIndices: [1, 2]},
      {innerText: 'Create image', tagName: 'SPAN', parentTag: 'P', promptLink: true, chipChildIndex: 2},
      {innerText: 'Create image', tagName: 'SPAN', parentTag: 'SPAN', promptLink: true}
    ]],
    ['non-prefix chip', [
      {innerText: `${expectedPrompt} Create image`, tagName: 'P', chipChildIndex: 1},
      {innerText: 'Create image', tagName: 'SPAN', parentTag: 'P', promptLink: true}
    ]],
    ['wrong chip text', [
      {innerText: `Create image tools ${expectedPrompt}`, tagName: 'P', chipChildIndex: 1},
      {innerText: 'Create image tools', tagName: 'SPAN', parentTag: 'P', promptLink: true}
    ]],
    ['value-only paragraph', [
      {value: validRenderedPrompt, tagName: 'P', chipChildIndex: 1},
      {innerText: 'Create image', tagName: 'SPAN', parentTag: 'P', promptLink: true}
    ]],
    ['textContent-only paragraph', [
      {textContent: validRenderedPrompt, tagName: 'P', chipChildIndex: 1},
      {innerText: 'Create image', tagName: 'SPAN', parentTag: 'P', promptLink: true}
    ]]
  ];

  for (const [name, userPromptDescendants] of cases) {
    const h = contentHarness({newUi: true, promptLinkBadge: true, chatPath, imageReady: true,
      conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: [outerBody, 'assistant reply'],
      userPromptDescendants});
    const accepted = await startCollect(h, 'Create image', 'draw a cat', {
      collect_only: true, output_binding_revision: 2, preserve_chat: true,
      recovery_chat_path: chatPath, images: originalImages
    });
    assert.ok(accepted?.accepted, name);
    await waitForContentResult(h);

    const result = h.sent.at(-1);
    assert.match(result.error, /prompt|binding|chip/i, name);
    assert.equal(result.imageBase64, undefined, `${name}: no image receipt`);
    assert.equal(result.imagesBase64, undefined, `${name}: no multi-image receipt`);
    assert.equal(result.promptBinding?.matcher_revision, 2, `${name}: revision diagnostic is bounded`);
    assert.equal(h.fetchCalls, 0, `${name}: no assistant image read`);
    assert.equal(h.sendClicks, 0, `${name}: no Send`);
    assert.equal(h.inputEvents.length, 0, `${name}: no upload`);
  }
});

test('submitted-job recovery refuses an unsupported output binding revision before reading images', async () => {
  const chatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const originalImages = [imageInput(1), imageInput(2)].map(({data_base64, ...metadata}) => metadata);
  const expectedPrompt = 'Create one image. Return a generated image, not just a description.\n' +
    'Actual attachments, in upload order:\nImage 1: REFERENCE GUIDANCE — reference 1\n' +
    'Image 2: REFERENCE GUIDANCE — reference 2\n\ndraw a cat';
  const h = contentHarness({newUi: true, chatPath, imageReady: true,
    conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: [expectedPrompt, 'assistant reply']});
  const accepted = await startCollect(h, 'Create image', 'draw a cat', {
    collect_only: true, output_binding_revision: 1, preserve_chat: true,
    recovery_chat_path: chatPath, images: originalImages
  });
  assert.ok(accepted?.accepted);
  await waitForContentResult(h);

  const result = h.sent.at(-1);
  assert.match(result.error, /revision|binding|prompt/i);
  assert.equal(result.imageBase64, undefined);
  assert.equal(result.imagesBase64, undefined);
  assert.equal(result.promptBinding?.matcher_revision, undefined);
  assert.equal(h.fetchCalls, 0, 'unsupported revision refuses before assistant image read');
  assert.equal(h.sendClicks, 0);
  assert.equal(h.inputEvents.length, 0);
});

test('failed submitted-job binding reports counts only and rejects substring, hidden, or textContent-only prompt matches', async () => {
  const chatPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const originalImages = [imageInput(1), imageInput(2)].map(({data_base64, ...metadata}) => metadata);
  const expectedPrompt = 'Create one image. Return a generated image, not just a description.\n' +
    'Actual attachments, in upload order:\nImage 1: REFERENCE GUIDANCE — reference 1\n' +
    'Image 2: REFERENCE GUIDANCE — reference 2\n\ndraw a cat';
  for (const [name, descendant] of [
    ['substring-only', {innerText: `prefix ${expectedPrompt} suffix`}],
    ['hidden exact text', {innerText: expectedPrompt, visible: false}],
    ['textContent-only', {textContent: expectedPrompt}]
  ]) {
    const h = contentHarness({newUi: true, chatPath, imageReady: true,
      conversationTurns: ['You said:', 'ChatGPT said:'],
      conversationBodies: [`Create image\nMessage controls\n${expectedPrompt}\nCopy`],
      userPromptDescendants: [descendant]});
    const accepted = await startCollect(h, 'Create image', 'draw a cat', {
      collect_only: true, preserve_chat: true, recovery_chat_path: chatPath, images: originalImages
    });
    assert.ok(accepted?.accepted, name);
    await waitForContentResult(h);

    const result = h.sent.at(-1);
    assert.match(result.error, /^Existing submitted-job recovery failed\. Existing conversation does not match this job's prompt/, name);
    assert.deepEqual(JSON.parse(JSON.stringify(result.promptBinding)), {
      root_match: false, exact_matching_descendant_count: 0,
      expected_chars: expectedPrompt.replace(/\s+/g, ' ').trim().length,
      observed_chars: result.promptBinding.observed_chars
    }, name);
    assert.deepEqual(Object.keys(result.promptBinding).sort(), [
      'exact_matching_descendant_count', 'expected_chars', 'observed_chars', 'root_match'
    ], `${name}: diagnostics contain counts, not prompt text`);
    assert.equal(h.fetchCalls, 0, `${name}: no assistant image read before prompt binding`);
    assert.equal(h.sendClicks, 0, `${name}: no Send`);
    assert.equal(h.inputEvents.length, 0, `${name}: no upload`);
  }
});

test('submitted-job recovery rejects a chat path mismatch before reading candidate images', async () => {
  const expectedPath = '/c/123e4567-e89b-12d3-a456-426614174000';
  const actualPath = '/c/223e4567-e89b-12d3-a456-426614174000';
  const originalImages = [imageInput(1), imageInput(2)].map(({data_base64, ...metadata}) => metadata);
  const originalPrompt = 'Create image Create one image. Return a generated image, not just a description.\n' +
    'Actual attachments, in upload order:\nImage 1: REFERENCE GUIDANCE — reference 1\n' +
    'Image 2: REFERENCE GUIDANCE — reference 2\n\ndraw a cat';
  const h = contentHarness({newUi: true, chatPath: actualPath, imageReady: true,
    conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: [originalPrompt]});
  const accepted = await startCollect(h, 'Create image', 'draw a cat', {
    collect_only: true, preserve_chat: true, recovery_chat_path: expectedPath, images: originalImages
  });
  assert.ok(accepted?.accepted);
  await waitForContentResult(h);

  const result = h.sent.at(-1);
  assert.match(result.error, /^Existing submitted-job recovery failed\. Existing result chat does not match this inspected job/);
  assert.equal(result.imageBase64, undefined);
  assert.equal(result.imagesBase64, undefined);
  assert.equal(h.fetchCalls, 0);
  assert.equal(h.sendClicks, 0);
  assert.equal(h.clicks, 0);
  assert.equal(h.sent.some(message => message.type === 'image-delete-prompt'), false);
});

test('collection-only refuses an existing user turn whose original prompt differs', async () => {
  const h = contentHarness({newUi: true,
    conversationTurns: ['You said:', 'ChatGPT said:'],
    conversationBodies: ['Create image Create one image. Return a generated image, not just a description.\n\ndraw something else']});
  await startCollect(h);
  assert.equal(h.editor.innerText, 'Create image');
  assert.equal(h.clicks, 0);
  assert.match(h.sent[0].error, /Existing conversation does not match this job's prompt/);
});

test('collection-only rejects a model mismatch and multiple existing turns without Send', async () => {
  for (const [options, expectedModel] of [
    [{conversationTurns: ['You said:', 'ChatGPT said:'], conversationBodies: ['Create image Create one image. Return a generated image, not just a description.\n\ndraw a cat']}, 'GPT-6 Thinking'],
    [{conversationTurns: ['You said:', 'ChatGPT said:', 'You said:', 'ChatGPT said:']}, 'Create image']
  ]) {
    const h = contentHarness({...options, newUi: true});
    const accepted = await startCollect(h, expectedModel);
    assert.ok(accepted?.accepted);
    assert.equal(h.editor.innerText, 'Create image');
    assert.equal(h.clicks, 0);
    assert.match(h.sent[0].error, /Wrong site or model|Inspect the completed single-turn/);
  }
});

test('collection-only refuses while Stop is visible', async () => {
  const h = contentHarness({newUi: true, busy: true,
    conversationTurns: ['You said:', 'ChatGPT said:']});
  await startCollect(h);
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.innerText, 'Create image');
  assert.match(h.sent[0].error, /Inspect the completed single-turn/);
});

test('visible verification before sending stops without editing or submitting', async () => {
  const h = contentHarness({challenge: true});
  await startContent(h);
  assert.equal(h.clicks, 0);
  assert.equal(h.editor.value, 'Create image');
  assert.match(h.sent[0].error, /Not submitted.*Owner action required/);
});

test('verification after sending stops for owner inspection without retry', async () => {
  const h = contentHarness({challengeAfterSend: true});
  await startContent(h);
  assert.equal(h.clicks, 1);
  assert.equal(h.sent.length, 1);
  assert.match(h.sent[0].error, /Submission attempted.*Owner action required/);
});

test('content listener reinjection is idempotent and ignores an unregistered stale marker', () => {
  const h = contentHarness();
  assert.equal(h.contentListenerCount, 1);
  h.rerunContent();
  assert.equal(h.contentListenerCount, 1);

  const stale = contentHarness({staleListenerMarker: true});
  assert.equal(stale.contentListenerCount, 1);
  stale.rerunContent();
  assert.equal(stale.contentListenerCount, 1);
});

function workerHarness({config = {token: 'x'.repeat(40), tabId: 7, clientId: 'client'}, active = {jobId: 'job-1', tabId: 7}} = {}) {
  let listener;
  const calls = [];
  const storage = {config, active};
  const chrome = {
    storage: {local: {
      async get(keys) { const out = {}; for (const key of (Array.isArray(keys) ? keys : [keys])) out[key] = storage[key]; return out; },
      async remove(key) { delete storage[key]; }, async set(value) { Object.assign(storage, value); }
    }},
    runtime: {getManifest: () => ({version: '0.1.12'}), onMessage: {addListener(fn) { listener = fn; }}},
    alarms: {onAlarm: {addListener() {}}, async clear() {}, async create() {}},
    tabs: {async sendMessage() {}}
  };
  const context = {chrome, URL, crypto: {randomUUID: () => 'id'}, AbortSignal,
    async fetch(url, options) { calls.push({url, body: JSON.parse(options.body)}); return {ok: true, json: async () => ({})}; }};
  vm.runInNewContext(workerSource, context, {filename: 'worker.js'});
  return {receive: listener, calls, storage};
}

test('worker rejects unknown or unpaired content results and preserves the active job', async t => {
  const cases = [
    ['unpaired sender', {id: 8, url: 'https://chatgpt.com/'} , 'job-1'],
    ['wrong job', {id: 7, url: 'https://chatgpt.com/'} , 'other-job'],
    ['wrong origin', {id: 7, url: 'https://example.com/'} , 'job-1']
  ];
  for (const [name, sender, jobId] of cases) await t.test(name, async () => {
    const h = workerHarness();
    let response;
    h.receive({type: 'image-result', jobId, imageBase64: 'not-a-real-image'}, sender, value => { response = value; });
    await new Promise(resolve => setImmediate(resolve));
    assert.match(response.error, /not from the paired job\/tab/);
    assert.equal(h.calls.length, 0);
    assert.equal(h.storage.active.jobId, 'job-1');
  });
});
