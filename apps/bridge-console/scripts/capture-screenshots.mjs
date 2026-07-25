import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "../../..");
const screenshotDirectory = resolve(repositoryRoot, "docs/assets/screenshots");
const consoleBaseUrl = process.env.BRIDGE_CONSOLE_URL ?? "http://127.0.0.1:8080";
const captures = [
  ["oss-console-overview.png", consoleBaseUrl],
  ["oss-console-accounts.png", `${consoleBaseUrl}/#accounts`],
  ["oss-console-docs.png", `${consoleBaseUrl}/#api-docs`],
  ["oss-console-library.png", `${consoleBaseUrl}/#storage`],
  ["oss-console-opencode.png", `${consoleBaseUrl}/#opencode`],
];

const visibleSecretPatterns = [
  /bearer\s+[^\s"'`]+/i,
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

async function capturePage(browser, filename, url) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
  try {
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
  for (const [filename, url] of captures) await capturePage(browser, filename, url);
} finally {
  await browser.close();
}
