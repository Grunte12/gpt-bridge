import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "../../..");
const screenshotDirectory = resolve(repositoryRoot, "docs/assets/screenshots");
const consoleBaseUrl = process.env.BRIDGE_CONSOLE_URL ?? "http://127.0.0.1:8080";
// Optional: seed the Console's stored API key so authenticated views (health,
// accounts, capacity) render instead of an offline/unauthorized empty state.
// Never pass a real account credential here; use a throwaway local key.
const consoleApiKey = process.env.BRIDGE_CONSOLE_API_KEY ?? "";
const captures = [
  ["oss-console-overview.png", consoleBaseUrl, { authenticate: true }],
  ["oss-console-accounts.png", `${consoleBaseUrl}/#accounts`, { authenticate: true }],
  // Left unauthenticated: this page's copy-paste curl examples embed the
  // live API key, which the redaction check below correctly refuses to
  // screenshot even when the key is just a local throwaway placeholder.
  ["oss-console-docs.png", `${consoleBaseUrl}/#api-docs`, { authenticate: false }],
  ["oss-console-library.png", `${consoleBaseUrl}/#storage`, { authenticate: true }],
  // Left unauthenticated: this page's copy-paste setup commands also embed
  // the live API key, same reasoning as the docs page above.
  ["oss-console-opencode.png", `${consoleBaseUrl}/#opencode`, { authenticate: false }],
];

const visibleSecretPatterns = [
  // Excludes plain-English UI copy like "bearer key applies when..." or
  // "Bearer key required/missing/does not match" so this only flags an
  // actual `Bearer <token>` value, not the word "key" describing the field.
  /bearer\s+(?!key\b)[^\s"'`]+/i,
  /(?:__secure-next-auth\.session-token|openai-sentinel(?:-[\w-]+)?|x-conduit-token)\s*[:=]\s*(?!<redacted>)[^\s;]+/i,
];

async function maskSensitiveFormValues(page) {
  await page.locator("input, textarea").evaluateAll((elements) => {
    for (const element of elements) {
      const value = element.value?.trim();
      if (!value) continue;
      const name = `${element.name} ${element.id} ${element.getAttribute("aria-label") ?? ""}`.toLowerCase();
      const looksSensitive =
        element.tagName === "TEXTAREA" ||
        /(?:api[ _-]?key|token|secret|cookie|authorization|capture|password)/.test(name) ||
        /(?:bearer\s+|__secure-next-auth|openai-sentinel|x-conduit-token)/i.test(value);
      if (looksSensitive) element.value = "<redacted>";
    }
  });
}

async function assertVisibleTextIsRedacted(page, filename) {
  const visibleText = await page.locator("body").innerText();
  const match = visibleSecretPatterns.map((pattern) => visibleText.match(pattern)).find(Boolean);
  if (match) {
    throw new Error(`${filename}: refusing to write a screenshot containing recognizable secret material (${match[0]}).`);
  }
}

async function capturePage(browser, filename, url, { authenticate = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
  try {
    if (authenticate && consoleApiKey) {
      await page.addInitScript((key) => {
        window.localStorage.setItem("chatgpt.console.apiKey", key);
      }, consoleApiKey);
    }
    await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });
    await maskSensitiveFormValues(page);
    await assertVisibleTextIsRedacted(page, filename);
    await page.screenshot({ path: resolve(screenshotDirectory, filename), fullPage: true });
    console.log(`captured ${filename}`);
  } finally {
    await page.close();
  }
}

await mkdir(screenshotDirectory, { recursive: true });
const browser = await chromium.launch();
try {
  for (const [filename, url, options] of captures) await capturePage(browser, filename, url, options);
} finally {
  await browser.close();
}
