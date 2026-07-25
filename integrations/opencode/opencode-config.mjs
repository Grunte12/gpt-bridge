#!/usr/bin/env bun

import { stdin as procStdin, stdout as procStdout } from "node:process";
import { createInterface } from "node:readline/promises";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1";
const DEFAULT_API_KEY = "";
const DEFAULT_MODEL = "chatgpt-web/auto@optimized";

const ansi = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  cyan: "\x1b[36m",
  green: "\x1b[32m",
  red: "\x1b[31m",
  yellow: "\x1b[33m",
};

const args = parseArgs(process.argv.slice(2));

main().catch((error) => {
  if (error instanceof BridgeConnectionError) {
    printConnectionHelp(error.baseUrl);
    process.exitCode = 1;
    return;
  }
  printError(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});

async function main() {
  const baseUrl =
    args.baseUrl || process.env.CHATGPT_OPENCODE_BASE_URL || DEFAULT_BASE_URL;
  const apiKey = args.apiKey || process.env.CHATGPT_API_KEY || DEFAULT_API_KEY;
  const model =
    args.model || process.env.CHATGPT_OPENCODE_MODEL || DEFAULT_MODEL;

  if (!args.action && !procStdin.isTTY) {
    throw new Error(
      "interactive mode requires a terminal; pass --inject, --eject, --status, or --action",
    );
  }

  const answers = args.action
    ? {
        action: args.action,
        baseUrl,
        apiKey,
        model,
        configPath: args.configPath || "",
      }
    : await promptForConfig({
        baseUrl,
        apiKey,
        model,
        configPath: args.configPath || "",
      });

  if (answers.action === "status") {
    const payload = await requestJson(
      answers.baseUrl,
      answers.apiKey,
      "GET",
      "/chatgpt/admin/opencode",
    );
    printResult("opencode status", payload);
    return;
  }

  if (answers.action === "inject") {
    const payload = await requestJson(
      answers.baseUrl,
      answers.apiKey,
      "POST",
      "/chatgpt/admin/opencode/inject",
      {
        base_url: answers.baseUrl,
        api_key: answers.apiKey,
        model: answers.model,
        config_path: answers.configPath || undefined,
      },
    );
    printResult("opencode injected", payload);
    return;
  }

  if (answers.action === "eject") {
    const payload = await requestJson(
      answers.baseUrl,
      answers.apiKey,
      "POST",
      "/chatgpt/admin/opencode/eject",
      {
        config_path: answers.configPath || undefined,
      },
    );
    printResult("opencode ejected", payload);
    return;
  }

  throw new Error(`unknown action: ${answers.action}`);
}

async function promptForConfig(defaults) {
  const action = await selectAction();
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  try {
    clear();
    header("opencode consumer config");
    line(
      "Scope",
      "Inject, eject, or inspect opencode config only. Account/server setup stays in the API console.",
    );
    line("Action", action);
    console.log("");

    const nextBaseUrl = await ask(rl, "Bridge API base URL", defaults.baseUrl);
    const nextApiKey =
      action === "eject"
        ? defaults.apiKey
        : await ask(rl, "Bearer key", defaults.apiKey);
    const nextModel =
      action === "inject"
        ? await ask(rl, "opencode model", defaults.model)
        : defaults.model;
    const configPath = await ask(
      rl,
      "opencode config path (blank = default)",
      defaults.configPath,
    );
    return {
      action,
      baseUrl: nextBaseUrl,
      apiKey: nextApiKey,
      model: nextModel,
      configPath,
    };
  } finally {
    rl.close();
  }
}

async function selectAction() {
  const options = [
    {
      value: "inject",
      title: "Inject",
      body: "Write opencode provider config that points at the bridge API.",
    },
    {
      value: "eject",
      title: "Eject",
      body: "Remove the generated ChatGPT provider block from opencode config.",
    },
    {
      value: "status",
      title: "Status",
      body: "Show what opencode config the API server currently sees.",
    },
  ];
  let selected = 0;
  renderActionMenu(options, selected);
  procStdin.setRawMode(true);
  procStdin.resume();
  procStdin.setEncoding("utf8");
  return await new Promise((resolve, reject) => {
    const cleanup = () => {
      procStdin.setRawMode(false);
      procStdin.off("data", onData);
    };
    const onData = (key) => {
      if (key === "\u0003") {
        cleanup();
        reject(new Error("cancelled"));
        return;
      }
      if (key === "\r" || key === "\n") {
        const value = options[selected].value;
        cleanup();
        resolve(value);
        return;
      }
      if (key === "\u001b[A" || key === "k") {
        selected = (selected - 1 + options.length) % options.length;
        renderActionMenu(options, selected);
        return;
      }
      if (key === "\u001b[B" || key === "j") {
        selected = (selected + 1) % options.length;
        renderActionMenu(options, selected);
      }
    };
    procStdin.on("data", onData);
  });
}

function renderActionMenu(options, selected) {
  clear();
  header("opencode consumer config");
  console.log(
    `${ansi.dim}Use ↑/↓ or j/k, then Enter. Ctrl-C cancels.${ansi.reset}\n`,
  );
  for (let index = 0; index < options.length; index += 1) {
    const option = options[index];
    const active = index === selected;
    const pointer = active ? `${ansi.cyan}›${ansi.reset}` : " ";
    const marker = active ? `${ansi.green}●${ansi.reset}` : "○";
    const title = active
      ? `${ansi.bold}${option.title}${ansi.reset}`
      : option.title;
    console.log(`${pointer} ${marker} ${title}`);
    console.log(`    ${ansi.dim}${option.body}${ansi.reset}`);
  }
  console.log("");
}

async function ask(rl, label, fallback) {
  const prompt = `${ansi.dim}${label}${fallback ? ` [${fallback}]` : ""}:${ansi.reset} `;
  const raw = await rl.question(prompt);
  return raw.trim() || fallback;
}

async function requestJson(baseUrl, apiKey, method, path, body) {
  const url = `${baseUrl.replace(/\/+$/, "")}${path}`;
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new BridgeConnectionError(baseUrl);
  }

  const text = await response.text();
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    const message =
      payload?.error?.message || text || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

function printResult(title, payload) {
  clear();
  header(title);
  const rows = [
    ["config", payload.config_path || "-"],
    ["injected", payload.injected ? "yes" : "no"],
    ["model", payload.model || "-"],
    ["base", payload.base_url || "-"],
  ];
  for (const [label, value] of rows) {
    line(label, value);
  }
  console.log("");
  console.log(JSON.stringify(payload, null, 2));
}

function printConnectionHelp(baseUrl) {
  clear();
  header("API server is offline");
  line("Tried", baseUrl);
  console.log("");
  console.log(
    `${ansi.yellow}Start the bridge API first, then rerun this opencode config command.${ansi.reset}\n`,
  );
  console.log("Local dev:");
  console.log(
    `  CHATGPT_API_KEY=YOUR_LOCAL_KEY gpt-bridge serve \\`,
  );
  console.log(`    --accounts free-main,pro-main --account-strategy failover \\`);
  console.log(`    --host 127.0.0.1 --port 8000 \\`);
  console.log(`    --public-base-url http://127.0.0.1:8000/v1\n`);
  console.log("Console UI:");
  console.log(`  bun --cwd apps/bridge-console dev\n`);
  console.log("Then:");
  console.log(
    `  bun integrations/opencode/opencode-config.mjs --base-url ${quote(baseUrl)} --api-key YOUR_LOCAL_KEY`,
  );
}

function printError(message) {
  clear();
  header("opencode config failed");
  console.log(`${ansi.red}${message}${ansi.reset}`);
}

function header(title) {
  console.log(
    `${ansi.bold}${ansi.cyan}GPT Bridge${ansi.reset} ${ansi.bold}${title}${ansi.reset}`,
  );
  console.log(
    `${ansi.dim}Only writes/removes opencode consumer config. It does not configure accounts or start the API server.${ansi.reset}\n`,
  );
}

function line(label, value) {
  console.log(`${ansi.dim}${label.padEnd(8)}${ansi.reset} ${value}`);
}

function clear() {
  procStdout.write("\x1b[2J\x1b[H");
}

function quote(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

class BridgeConnectionError extends Error {
  constructor(baseUrl) {
    super(`Unable to connect to ${baseUrl}`);
    this.baseUrl = baseUrl;
  }
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--action") {
      parsed.action = next;
      index += 1;
    } else if (arg === "--base-url") {
      parsed.baseUrl = next;
      index += 1;
    } else if (arg === "--api-key") {
      parsed.apiKey = next;
      index += 1;
    } else if (arg === "--model") {
      parsed.model = next;
      index += 1;
    } else if (arg === "--config-path") {
      parsed.configPath = next;
      index += 1;
    } else if (arg === "--inject") {
      parsed.action = "inject";
    } else if (arg === "--eject") {
      parsed.action = "eject";
    } else if (arg === "--status") {
      parsed.action = "status";
    }
  }
  return parsed;
}
