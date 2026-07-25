#!/usr/bin/env bun

import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { stdin as procStdin, stdout as procStdout } from "node:process";
import { createInterface } from "node:readline/promises";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "../..");
const defaultConfigPath = resolve(scriptDir, "opencode.example.json");
const defaultApiHost = "127.0.0.1";
const defaultApiPort = "8000";
const defaultBaseURL = "http://127.0.0.1:8000/v1";
const defaultApiKey = "";
const defaultConfigHome = resolve(process.env.XDG_CONFIG_HOME || resolve(homedir(), ".config"));
const defaultInstallConfigPath = resolve(defaultConfigHome, "opencode", "opencode.json");
const defaultStatePath = resolve(defaultConfigHome, "gpt-bridge", "opencode-setup.json");
const legacyStatePath = resolve(defaultConfigHome, "chatgpt-api", "opencode-setup.json");
const ansi = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  cyan: "\x1b[36m",
  green: "\x1b[32m",
  magenta: "\x1b[35m",
  yellow: "\x1b[33m",
  red: "\x1b[31m",
};

const rawArgs = process.argv.slice(2);
const parsed = parseArgs(rawArgs);

if (shouldRunConsumerConfig(rawArgs, parsed)) {
  await runConsumerConfig(parsed, rawArgs);
} else {
  await runOpencode(parsed);
}

function shouldRunConsumerConfig(rawArgs, parsedArgs) {
  if (rawArgs.length === 0 || parsedArgs.setup) {
    return true;
  }
  return rawArgs.some((arg) => ["--inject", "--eject", "--status"].includes(arg) || arg.startsWith("--action"));
}

async function runConsumerConfig(parsedArgs, rawArgs) {
  const command = ["bun", resolve(scriptDir, "opencode-config.mjs")];
  if (rawArgs.includes("--inject")) {
    command.push("--inject");
  } else if (rawArgs.includes("--eject")) {
    command.push("--eject");
  } else if (rawArgs.includes("--status")) {
    command.push("--status");
  } else if (parsedArgs.yes) {
    command.push("--inject");
  }
  if (parsedArgs.baseURL) {
    command.push("--base-url", parsedArgs.baseURL);
  }
  if (parsedArgs.apiKey) {
    command.push("--api-key", parsedArgs.apiKey);
  }
  if (parsedArgs.model) {
    command.push("--model", applyAgentMode(normalizeProviderModel(parsedArgs.model), parsedArgs.agentMode || "optimized"));
  }
  if (parsedArgs.installConfigPath) {
    command.push("--config-path", parsedArgs.installConfigPath);
  }
  const child = Bun.spawn(command, {
    stdin: "inherit",
    stdout: "inherit",
    stderr: "inherit",
    env: process.env,
  });
  process.exitCode = await child.exited;
}

async function runOpencode(parsedArgs) {
  const state = readJsonIfExists(resolveStatePath(parsedArgs.statePath));
  const baseModel =
    parsedArgs.model ||
    process.env.CHATGPT_OPENCODE_MODEL ||
    state.base_model ||
    "chatgpt-web/auto";
  const agentMode =
    parsedArgs.agentMode ||
    process.env.CHATGPT_OPENCODE_AGENT_MODE ||
    process.env.CHATGPT_AGENT_MODE ||
    state.agent_mode ||
    "optimized";
  const model = applyAgentMode(normalizeProviderModel(baseModel), agentMode);
  const apiKey = parsedArgs.apiKey || process.env.CHATGPT_API_KEY || state.api_key || defaultApiKey;
  const baseURL = parsedArgs.baseURL || process.env.CHATGPT_OPENCODE_BASE_URL || state.base_url || defaultBaseURL;
  const configPath = resolve(parsedArgs.configPath || defaultConfigPath);
  const tempDir = mkdtempSync(resolve(tmpdir(), "gpt-bridge-opencode-"));
  const tempConfigPath = resolve(tempDir, "opencode.json");

  try {
    const config = buildOpencodeConfig(readJsonFile(configPath), { apiKey, baseURL, model });
    const configContent = `${JSON.stringify(config, null, 2)}\n`;
    writeFileSync(tempConfigPath, configContent);

    const command = [
      "bunx",
      "--bun",
      "opencode-ai",
      ...(parsedArgs.pure ? ["--pure"] : []),
      ...(parsedArgs.debugConfig ? ["debug", "config"] : ["--model", model, parsedArgs.project]),
      ...parsedArgs.passThrough,
    ];

    if (parsedArgs.dryRun) {
      console.log(`OPENCODE_CONFIG=${tempConfigPath}`);
      console.log(`CHATGPT_API_KEY=${apiKey ? "<set>" : "<empty>"}`);
      console.log(`CHATGPT_AGENT_MODE=${agentMode || "<server-default>"}`);
      console.log(command.join(" "));
      process.exit(0);
    }

    const child = Bun.spawn(command, {
      stdin: "inherit",
      stdout: "inherit",
      stderr: "inherit",
      env: {
        ...process.env,
        OPENCODE_CONFIG: tempConfigPath,
        OPENCODE_CONFIG_CONTENT: configContent,
        CHATGPT_API_KEY: apiKey,
      },
    });
    process.exitCode = await child.exited;
  } finally {
    if (!parsedArgs.keepConfig) {
      rmSync(tempDir, { recursive: true, force: true });
    } else {
      console.error(`kept OPENCODE_CONFIG at ${tempConfigPath}`);
    }
  }
}

async function runSetup(parsedArgs) {
  if (!parsedArgs.yes && !procStdin.isTTY) {
    throw new Error("interactive setup requires a TTY; use setup --yes for defaults");
  }

  const discoveredAccounts = discoverAccountProfiles();
  const apiBaseURL = parsedArgs.baseURL || baseURLForApi(parsedArgs.apiHost, parsedArgs.apiPort);
  const defaults = {
    account: parsedArgs.account || (discoveredAccounts.includes("free") ? "free" : discoveredAccounts[0] || "free"),
    accounts: splitCsv(parsedArgs.accounts),
    agentMode: parsedArgs.agentMode || "optimized",
    apiKey: parsedArgs.apiKey || process.env.CHATGPT_API_KEY || defaultApiKey,
    baseModel: parsedArgs.model || "chatgpt-web/auto",
    baseURL: apiBaseURL,
    chatMode: parsedArgs.chatMode || "temporary",
    imageOutputDir: parsedArgs.imageOutputDir || "./outputs/chatgpt-images",
    researchOutputDir: parsedArgs.researchOutputDir || "./outputs/chatgpt-research",
    installConfigPath: resolve(parsedArgs.installConfigPath || defaultInstallConfigPath),
    limitStrategy: parsedArgs.limitStrategy || "auto",
    modelFallback: parsedArgs.modelFallback || "auto",
    statePath: resolveStatePath(parsedArgs.statePath),
  };

  let answers = { ...defaults };
  if (!parsedArgs.yes) {
    answers = await promptForSetup(defaults, discoveredAccounts);
  }

  const selectedAccounts = answers.accounts.length
    ? answers.accounts
    : parsedArgs.multiAccount && discoveredAccounts.length
      ? discoveredAccounts
      : [answers.account];
  const modelPolicy = modelPolicyForAccounts(selectedAccounts);
  if (modelPolicy.autoOnly) {
    answers.baseModel = "chatgpt-web/auto";
  }
  const accountMode = parsedArgs.multiAccount || selectedAccounts.length > 1 ? "multi" : "single";
  const model = applyAgentMode(normalizeProviderModel(answers.baseModel), answers.agentMode);
  const installConfig = buildOpencodeConfig(readJsonIfExists(answers.installConfigPath), {
    apiKey: answers.apiKey,
    baseURL: answers.baseURL,
    model,
  });

  writeJsonWithBackup(answers.installConfigPath, installConfig);
  writeJsonWithBackup(answers.statePath, {
    version: 1,
    updated_at: new Date().toISOString(),
    base_url: answers.baseURL,
    api_key: answers.apiKey,
    api: {
      base_url: answers.baseURL,
      note: "This only controls where opencode connects. It does not bind or start the API server.",
    },
    base_model: normalizeProviderModel(answers.baseModel),
    resolved_model: model,
    agent_mode: answers.agentMode,
    chat_mode: answers.chatMode,
    temporary_chat: answers.chatMode !== "normal",
    model_fallback: answers.modelFallback,
    opencode_config_path: answers.installConfigPath,
    accounts: {
      mode: accountMode,
      selected: selectedAccounts,
      profiles: modelPolicy.profiles,
      limit_strategy: answers.limitStrategy,
      model_policy: modelPolicy.autoOnly ? "auto-only" : "model-aware-routing",
      model_policy_reason: modelPolicy.reason,
      note: "Start the API with --accounts and --account-strategy to enable server-side multi-account routing.",
    },
    images: {
      status: "available",
      output_dir: answers.imageOutputDir,
      api_route: "/v1/images/generations",
      chat_mode: "normal",
      save_policy: "Ask the user unless the prompt gives an explicit output path.",
      note: "Image generation uses normal ChatGPT mode because temporary/private chats do not support image creation.",
    },
    research: {
      status: "available",
      output_dir: answers.researchOutputDir,
      api_route: "/v1/chat/completions",
      model: "chatgpt-web/chatgpt-deep-research",
      chat_mode: "normal",
      command: "/chatgpt:research",
      limit_policy: "The API checks ChatGPT conversation/init before starting and skips accounts with exhausted Deep Research quota.",
      note: "Deep Research uses normal ChatGPT chat mode because temporary/private chats do not support it.",
    },
    commands: {
      usage: "/chatgpt:usage",
      remain: "/chatgpt:remain",
      research: "/chatgpt:research",
    },
    attachments: {
      image_upload: false,
      file_upload: false,
      policy: "Do not upload attachments to ChatGPT Web. Pass local paths and let opencode tools read/search files.",
    },
  });

  console.log("");
  console.log("Setup complete");
  console.log("==============");
  console.log(`opencode config  ${answers.installConfigPath}`);
  console.log(`setup state      ${answers.statePath}`);
  console.log(`opencode URL     ${answers.baseURL}`);
  console.log(`model            ${model}`);
  console.log(`model fallback   ${answers.modelFallback}`);
  console.log(`chat mode        ${answers.chatMode}`);
  console.log("image mode       normal (temporary/private chats cannot create images)");
  console.log(`research output  ${answers.researchOutputDir}`);
  console.log(`accounts         ${selectedAccounts.join(", ")} (${accountMode}, ${answers.limitStrategy})`);
  console.log(`model policy     ${modelPolicy.autoOnly ? "auto-only" : "model-aware-routing"}`);
  console.log(`reason           ${modelPolicy.reason}`);
  console.log("commands         /chatgpt:usage  /chatgpt:remain  /chatgpt:research");
  console.log("");
  console.log("Start the API if it is not already running:");
  console.log(serverCommand({
    apiKey: answers.apiKey,
    accounts: selectedAccounts,
    strategy: answers.limitStrategy,
    agentMode: answers.agentMode,
    modelFallback: answers.modelFallback,
    chatMode: answers.chatMode,
    imageOutputDir: answers.imageOutputDir,
    researchOutputDir: answers.researchOutputDir,
    port: portFromBaseURL(answers.baseURL),
  }));
  console.log("");
  console.log("Then open opencode normally:");
  console.log("opencode .");
  console.log("");
  console.log("If `opencode` is not installed on this machine:");
  console.log("bun install -g opencode-ai");
  console.log("or use: bunx --bun opencode-ai .");
}

async function promptForSetup(defaults, discoveredAccounts) {
  const rl = createInterface({ input: procStdin, output: procStdout });
  try {
    const state = { discoveredAccounts, answers: {} };
    const preset = await askChoiceScreen(rl, state, "Preset", "quick", ["quick", "agent", "custom"]);
    const presetDefaults = applyPresetDefaults(defaults, preset, discoveredAccounts);
    state.answers.preset = preset;

    const accountDefault = presetDefaults.accounts.length
      ? presetDefaults.accounts.join(",")
      : presetDefaults.account;
    const selectedAccounts = discoveredAccounts.length
      ? await askAccountsScreen(rl, state, accountDefault, discoveredAccounts)
      : parseAccountSelection(
          await askScreen(rl, state, "Accounts to use", accountDefault, "No captures found yet; type the account name to use."),
          discoveredAccounts,
          accountDefault,
        );
    state.answers.accounts = selectedAccounts.join(", ");
    const modelPolicy = modelPolicyForAccounts(selectedAccounts);
    state.accountProfiles = modelPolicy.profiles;
    if (modelPolicy.autoOnly) {
      state.answers.modelPolicy = "auto-only";
    }
    const accountMode = selectedAccounts.length > 1 ? "multi" : "single";
    const limitStrategyDefault = accountMode === "multi" ? "failover" : presetDefaults.limitStrategy;
    const limitStrategy = await askChoiceScreen(rl, state, "Limit strategy", limitStrategyDefault, [
      "auto",
      "sticky",
      "failover",
      "round-robin",
      "weighted",
      "quota-aware",
    ]);
    state.answers.strategy = limitStrategy;
    const agentMode = await askChoiceScreen(rl, state, "Agent prompt mode", presetDefaults.agentMode, ["optimized", "opencode"]);
    state.answers.agentMode = agentMode;
    const baseModel = await askModelScreen(rl, state, presetDefaults.baseModel, modelPolicy);
    state.answers.model = baseModel;
    const modelFallback = await askChoiceScreen(rl, state, "Model fallback", presetDefaults.modelFallback || "auto", ["auto", "none"]);
    state.answers.modelFallback = modelFallback;
    const chatMode = await askChoiceScreen(rl, state, "Chat privacy", presetDefaults.chatMode || "temporary", ["temporary", "normal"]);
    state.answers.chatMode = chatMode;
    const installConfigPath = await askScreen(rl, state, "opencode config path", defaults.installConfigPath);
    const baseURL = await askScreen(rl, state, "Local API base URL", presetDefaults.baseURL);
    const apiKey = await askScreen(rl, state, "Local API key", defaults.apiKey);
    const imageOutputDir = await askScreen(rl, state, "Image output directory", presetDefaults.imageOutputDir);
    const researchOutputDir = await askScreen(rl, state, "Research output directory", presetDefaults.researchOutputDir);
    clearSetupScreen();
    return {
      ...presetDefaults,
      account: selectedAccounts[0] || presetDefaults.account,
      accounts: selectedAccounts,
      agentMode,
      apiKey,
      baseModel,
      baseURL,
      chatMode,
      imageOutputDir,
      researchOutputDir,
      installConfigPath: resolve(installConfigPath),
      limitStrategy,
      modelFallback,
    };
  } finally {
    rl.close();
  }
}

function printAccountTable(accounts) {
  console.log("Detected accounts");
  console.log("-----------------");
  if (!accounts.length) {
    console.log("No captures found under secrets/accounts yet.");
    console.log("You can still set up opencode now and add captures later.");
    return;
  }
  for (const [index, account] of accounts.entries()) {
    console.log(`${String(index + 1).padStart(2, " ")}  ${account}`);
  }
}

function clearSetupScreen() {
  if (procStdout.isTTY) {
    procStdout.write("\x1b[2J\x1b[H");
  }
}

function paint(code, value) {
  if (!procStdout.isTTY || process.env.NO_COLOR) {
    return String(value);
  }
  return `${code}${value}${ansi.reset}`;
}

function setupFrame(state, title) {
  clearSetupScreen();
  console.log(`${paint(ansi.bold + ansi.cyan, "ChatGPT opencode")} ${paint(ansi.dim, "setup")}`);
  console.log(`${paint(ansi.dim, "accounts")} ${formatAccountPills(state.discoveredAccounts)}`);
  if (state.accountProfiles?.length) {
    console.log(`${paint(ansi.dim, "plans   ")} ${formatAccountPlanPills(state.accountProfiles)}`);
  }
  const progress = formatProgressSummary(state.answers);
  if (progress) {
    console.log(`${paint(ansi.dim, "steps   ")} ${progress}`);
  }
  console.log("");
  console.log(paint(ansi.bold + ansi.magenta, title));
  console.log("");
}

function formatAccountPills(accounts) {
  if (!accounts.length) {
    return paint(ansi.yellow, "no captures yet");
  }
  return accounts.map((account, index) => paint(ansi.cyan, `[${index + 1}] ${account}`)).join("  ");
}

function formatAnswerSummary(answers) {
  const parts = [];
  if (answers.preset) parts.push(`preset=${answers.preset}`);
  if (answers.accounts) parts.push(`accounts=${answers.accounts}`);
  if (answers.strategy) parts.push(`strategy=${answers.strategy}`);
  if (answers.agentMode) parts.push(`prompt=${answers.agentMode}`);
  if (answers.model) parts.push(`model=${answers.model}`);
  if (answers.modelFallback) parts.push(`fallback=${answers.modelFallback}`);
  if (answers.modelPolicy) parts.push(`policy=${answers.modelPolicy}`);
  return parts.join("  ");
}

function formatProgressSummary(answers) {
  const steps = [
    ["Preset", answers.preset],
    ["Accounts", answers.accounts],
    ["Strategy", answers.strategy],
    ["Prompt", answers.agentMode],
    ["Model", answers.model],
    ["Privacy", answers.chatMode],
  ];
  return steps
    .filter(([, value]) => value)
    .map(([label, value]) => `${paint(ansi.green, label)}=${value}`)
    .join("  ");
}

async function askScreen(rl, state, label, defaultValue, help = "") {
  const fieldHelp = help || textInputHelp(label);
  setupFrame(state, label);
  if (fieldHelp) {
    console.log(paint(ansi.dim, fieldHelp));
    console.log("");
  }
  const answer = await rl.question(`${paint(ansi.green, "›")} ${label} ${paint(ansi.dim, `[${defaultValue}]`)}: `);
  return answer.trim() || defaultValue;
}

async function askChoiceScreen(rl, state, label, defaultValue, choices, help = "") {
  if (procStdin.isTTY && typeof procStdin.setRawMode === "function") {
    return selectChoiceScreen(rl, state, label, defaultValue, choices, help || choiceHelp(label));
  }
  for (;;) {
    const settingHelp = help || choiceHelp(label);
    setupFrame(state, label);
    for (const [index, choice] of choices.entries()) {
      const selected = choice === defaultValue;
      const marker = selected ? "●" : "○";
      const line = `${index + 1}. ${marker} ${choice}`;
      console.log(selected ? paint(ansi.green + ansi.bold, line) : `   ${line}`);
    }
    renderFooterHelp(settingHelp, "Type number/name · Enter keep default", choiceDescription(label, defaultValue, state));
    const answer = await rl.question(`${paint(ansi.green, "›")} choose 1-${choices.length} or name ${paint(ansi.dim, `[${defaultValue}]`)}: `);
    const normalized = answer.trim().toLowerCase();
    if (!normalized) {
      return defaultValue;
    }
    if (/^\d+$/.test(normalized)) {
      const selected = choices[Number(normalized) - 1];
      if (selected) {
        return selected;
      }
    }
    if (choices.includes(normalized)) {
      return normalized;
    }
  }
}

async function askAccountsScreen(rl, state, accountDefault, discoveredAccounts) {
  const defaults = parseAccountSelection(accountDefault, discoveredAccounts, accountDefault);
  if (procStdin.isTTY && typeof procStdin.setRawMode === "function") {
    return selectMultiChoiceScreen(
      rl,
      state,
      "Accounts to use",
      defaults,
      discoveredAccounts,
      "Use Space to enable/disable accounts. Multiple accounts enable failover and model-aware routing.",
    );
  }
  const accountAnswer = await askScreen(
    rl,
    state,
    "Accounts to use",
    discoveredAccounts.length > 1 ? "all" : accountDefault,
    "Use all, 1,2, or account names. Multi-account enables failover.",
  );
  return parseAccountSelection(accountAnswer, discoveredAccounts, accountDefault);
}

function selectChoiceScreen(rl, state, label, defaultValue, choices, help = "") {
  let cursor = Math.max(choices.indexOf(defaultValue), 0);
  return readRawSelection(rl, () => {
    setupFrame(state, label);
    for (const [index, choice] of choices.entries()) {
      const focused = index === cursor;
      const marker = focused ? "●" : "○";
      const prefix = focused ? "›" : " ";
      const line = `${prefix} ${index + 1}. ${marker} ${choice}`;
      console.log(focused ? paint(ansi.green + ansi.bold, line) : line);
    }
    renderFooterHelp(help, "↑/↓ move · Enter select · 1-9 jump · Ctrl-C cancel", choiceDescription(label, choices[cursor], state));
  }, (key, done) => {
    if (key === "up") {
      cursor = (cursor - 1 + choices.length) % choices.length;
      return;
    }
    if (key === "down") {
      cursor = (cursor + 1) % choices.length;
      return;
    }
    if (key === "enter") {
      done(choices[cursor]);
      return;
    }
    if (/^[1-9]$/.test(key)) {
      const index = Number(key) - 1;
      if (choices[index]) {
        cursor = index;
        done(choices[cursor]);
      }
    }
  });
}

function selectMultiChoiceScreen(rl, state, label, defaultValues, choices, help = "") {
  let cursor = 0;
  const selected = new Set(defaultValues.filter((value) => choices.includes(value)));
  if (!selected.size && choices[0]) {
    selected.add(choices[0]);
  }
  return readRawSelection(rl, () => {
    setupFrame(state, label);
    for (const [index, choice] of choices.entries()) {
      const focused = index === cursor;
      const checked = selected.has(choice);
      const prefix = focused ? "›" : " ";
      const box = checked ? "■" : "□";
      const line = `${prefix} ${index + 1}. ${box} ${choice}`;
      console.log(focused ? paint(ansi.green + ansi.bold, line) : line);
    }
    renderFooterHelp(help, "↑/↓ move · Space toggle · A all/one · Enter confirm · Ctrl-C cancel", choiceDescription(label, choices[cursor], state));
  }, (key, done) => {
    if (key === "up") {
      cursor = (cursor - 1 + choices.length) % choices.length;
      return;
    }
    if (key === "down") {
      cursor = (cursor + 1) % choices.length;
      return;
    }
    if (key === "space") {
      const choice = choices[cursor];
      if (selected.has(choice)) {
        selected.delete(choice);
      } else {
        selected.add(choice);
      }
      return;
    }
    if (key === "a") {
      if (selected.size === choices.length) {
        selected.clear();
        selected.add(choices[cursor]);
      } else {
        choices.forEach((choice) => selected.add(choice));
      }
      return;
    }
    if (/^[1-9]$/.test(key)) {
      const index = Number(key) - 1;
      if (choices[index]) {
        cursor = index;
      }
      return;
    }
    if (key === "enter") {
      if (!selected.size && choices[cursor]) {
        selected.add(choices[cursor]);
      }
      done(choices.filter((choice) => selected.has(choice)));
    }
  });
}

function readRawSelection(rl, render, onKey) {
  return new Promise((resolve) => {
    const wasRaw = procStdin.isRaw;
    let finished = false;
    const finish = (value) => {
      finished = true;
      procStdin.off("data", handleData);
      procStdin.setRawMode(Boolean(wasRaw));
      rl.resume();
      clearSetupScreen();
      resolve(value);
    };
    const handleData = (chunk) => {
      const key = normalizeKey(chunk);
      if (key === "ctrl-c") {
        procStdin.setRawMode(false);
        procStdout.write("\n");
        process.exit(130);
      }
      onKey(key, finish);
      if (!finished) {
        render();
      }
    };
    rl.pause();
    procStdin.setRawMode(true);
    procStdin.resume();
    procStdin.on("data", handleData);
    render();
  });
}

function normalizeKey(chunk) {
  const value = chunk.toString("utf8");
  if (value === "\u0003") return "ctrl-c";
  if (value === "\r" || value === "\n") return "enter";
  if (value === " ") return "space";
  if (value === "\u001b[A" || value === "k") return "up";
  if (value === "\u001b[B" || value === "j") return "down";
  return value.toLowerCase();
}

function renderFooterHelp(help, keys, detail = "") {
  console.log("");
  console.log(paint(ansi.dim, keys));
  if (detail) {
    console.log(`${paint(ansi.dim, "Selected:")} ${detail}`);
  }
  if (help) {
    console.log(`${paint(ansi.dim, "Setting:")} ${help}`);
  }
  console.log("");
}

async function askModelScreen(rl, state, defaultModel, policy = modelPolicyForAccounts([])) {
  if (policy.autoOnly) {
    await askChoiceScreen(
      rl,
      state,
      "Model group",
      "auto",
      ["auto"],
      `${policy.reason} ChatGPT Web Auto lets the web app pick an available model after limits or downgrades.`,
    );
    return "chatgpt-web/auto";
  }
  const defaults = modelDefaults(defaultModel);
  const group = await askChoiceScreen(
    rl,
    state,
    "Model group",
    defaults.group,
    ["auto", "gpt-5.5", "thinking", "pro", "sol-high"],
    "Choose the model family first. Effort appears only inside Thinking or Pro. Sol High requires capture/settings evidence.",
  );
  if (group === "auto") {
    return "chatgpt-web/auto";
  }
  if (group === "gpt-5.5") {
    return "chatgpt-web/gpt-5-5";
  }
  if (group === "sol-high") {
    return "chatgpt-web/gpt-5-6-sol-high";
  }
  if (group === "thinking") {
    const effort = await askChoiceScreen(
      rl,
      state,
      "Thinking effort",
      defaults.thinkingEffort,
      ["standard", "extended", "max"],
      "Standard is lighter. Extended/Max are stronger but hit limits faster.",
    );
    return `chatgpt-web/gpt-5-5-thinking-${effort}`;
  }
  const effort = await askChoiceScreen(
    rl,
    state,
    "Pro effort",
    defaults.proEffort,
    ["standard", "extended"],
    "Pro Extended is strongest, but fallback should usually stay on auto.",
  );
  return `chatgpt-web/gpt-5-5-pro-${effort}`;
}

function modelDefaults(model) {
  const id = normalizeProviderModel(model).split("/", 2)[1] || "auto";
  if (id.startsWith("gpt-5-6-sol-high")) {
    return { group: "sol-high", thinkingEffort: "extended", proEffort: "extended" };
  }
  if (id.startsWith("gpt-5-5-pro")) {
    return { group: "pro", thinkingEffort: "extended", proEffort: id.endsWith("standard") ? "standard" : "extended" };
  }
  if (id.startsWith("gpt-5-5-thinking")) {
    const effort = id.endsWith("max") ? "max" : id.endsWith("standard") ? "standard" : "extended";
    return { group: "thinking", thinkingEffort: effort, proEffort: "extended" };
  }
  if (id === "gpt-5-5") {
    return { group: "gpt-5.5", thinkingEffort: "extended", proEffort: "extended" };
  }
  return { group: "auto", thinkingEffort: "extended", proEffort: "extended" };
}

function choiceHelp(label) {
  if (label === "Preset") {
    return "Controls the initial defaults. You can still change the important settings after this screen.";
  }
  if (label === "Accounts to use") {
    return "Controls which ChatGPT captures the local API can route through.";
  }
  if (label === "Limit strategy") {
    return "Controls how the local API chooses accounts when more than one account is enabled.";
  }
  if (label === "Agent prompt mode") {
    return "Controls how much opencode/tool instruction text is sent to ChatGPT on every request.";
  }
  if (label === "Model group") {
    return "Controls the ChatGPT Web model family. Free/Go accounts are shown as Auto only.";
  }
  if (label === "Thinking effort") {
    return "Controls the Thinking sub-mode for GPT-5.5 Thinking accounts.";
  }
  if (label === "Pro effort") {
    return "Controls the Pro sub-mode for GPT-5.5 Pro accounts.";
  }
  if (label === "Model fallback") {
    return "Controls what happens when an explicit model returns a recoverable model-limit or empty-text error.";
  }
  if (label === "Chat privacy") {
    return "Controls whether normal chat requests use temporary/private ChatGPT conversations.";
  }
  return "";
}

function choiceDescription(label, choice, state = {}) {
  const normalized = String(choice || "").toLowerCase();
  if (label === "Preset") {
    if (normalized === "quick") {
      return "Recommended default. Uses the compact optimized prompt and ChatGPT Auto, good for POC work, small edits, and free-account testing.";
    }
    if (normalized === "agent") {
      return "Keeps more of opencode's native agent instructions. Better for complex coding tasks, but heavier and more likely to hit web limits.";
    }
    if (normalized === "custom") {
      return "Starts from your current/manual defaults and lets you choose each setting yourself.";
    }
  }
  if (label === "Accounts to use") {
    return accountChoiceDescription(choice, state);
  }
  if (label === "Limit strategy") {
    if (normalized === "auto") {
      return "Server default. Single account stays simple; multiple accounts use conservative routing without you choosing every detail.";
    }
    if (normalized === "sticky") {
      return "Always tries the first selected account first. Predictable, but can keep hitting the same limited account.";
    }
    if (normalized === "failover") {
      return "Best default for multiple accounts. If one account hits model/limit/empty-text errors, the next selected account is tried.";
    }
    if (normalized === "round-robin") {
      return "Rotates account order across requests to spread usage more evenly.";
    }
    if (normalized === "weighted") {
      return "Rotates accounts but favors names/plans that look higher tier, such as pro or plus.";
    }
    if (normalized === "quota-aware") {
      return "Limit-aware mode reserved for richer quota data; currently behaves conservatively with error-based fallback.";
    }
  }
  if (label === "Agent prompt mode") {
    if (normalized === "optimized") {
      return "Short bridge prompt. Usually better for proof-of-concept agent use because it saves tokens and reduces instruction noise.";
    }
    if (normalized === "opencode") {
      return "Fuller prompt closer to opencode's original instructions. Can improve tool discipline, but costs more context every turn.";
    }
  }
  if (label === "Model group") {
    if (normalized === "auto") {
      return "ChatGPT Web Auto. Safest default because the web app can pick or retry an available model when explicit models are limited.";
    }
    if (normalized === "gpt-5.5") {
      return "Explicit core GPT-5.5. Good when a selected account supports it and quota is still available.";
    }
    if (normalized === "thinking") {
      return "Explicit GPT-5.5 Thinking. More capable for hard coding tasks, but slower and more likely to hit limits.";
    }
    if (normalized === "pro") {
      return "Explicit GPT-5.5 Pro. Requires a Pro-capable account and is the most limit-sensitive choice.";
    }
    if (normalized === "sol-high") {
      return "GPT-5.6 Sol High. Available only when the selected account capture or settings observed the verified backend model and effort.";
    }
  }
  if (label === "Thinking effort") {
    if (normalized === "standard") {
      return "Lighter Thinking mode. Faster and less quota-sensitive than extended or max.";
    }
    if (normalized === "extended") {
      return "Stronger Thinking mode. Better for non-trivial agent tasks, with higher limit risk.";
    }
    if (normalized === "max") {
      return "Highest Thinking effort exposed here. Use for hard tasks only; it has the highest chance of limit or empty-response failures.";
    }
  }
  if (label === "Pro effort") {
    if (normalized === "standard") {
      return "Pro Standard. Safer than Extended while still routing to the Pro model family.";
    }
    if (normalized === "extended") {
      return "Pro Extended. Strongest Pro mode, but the most likely to need Auto fallback when quota is tight.";
    }
  }
  if (label === "Model fallback") {
    if (normalized === "auto") {
      return "Recommended. If an explicit model fails recoverably, retry once through ChatGPT Web Auto before showing an error in opencode.";
    }
    if (normalized === "none") {
      return "Strict mode. Do not switch models; opencode will see the original model error.";
    }
  }
  if (label === "Chat privacy") {
    if (normalized === "temporary") {
      return "Default. Sends chat requests with history/training disabled, useful for coding privacy and test prompts.";
    }
    if (normalized === "normal") {
      return "Normal ChatGPT chat mode. Use only when you want normal web history behavior; image generation already uses normal mode internally.";
    }
  }
  return "";
}

function accountChoiceDescription(account, state = {}) {
  const profile = cachedAccountProfile(account, state);
  const plan = profile.plan || "unknown";
  const source = profile.source || "unknown";
  if (["free", "go"].includes(plan)) {
    return `${account}: ${plan} plan (${source}). This account is treated as ChatGPT Web Auto only; explicit GPT-5.5/Thinking/Pro can fail or downgrade in the web flow.`;
  }
  if (["pro", "plus", "team", "enterprise"].includes(plan)) {
    return `${account}: ${plan} plan (${source}). Can be used for explicit model routing when quota allows; fallback still protects opencode from empty responses.`;
  }
  return `${account}: plan unknown (${source}). Setup keeps explicit models visible until a capture or live check proves this account is Auto-only.`;
}

function cachedAccountProfile(account, state = {}) {
  state.accountProfileCache ||= {};
  if (!state.accountProfileCache[account]) {
    state.accountProfileCache[account] = accountPlanProfile(account);
  }
  return state.accountProfileCache[account];
}

function textInputHelp(label) {
  if (label === "opencode config path") {
    return "Where setup writes opencode's normal config. After this, daily usage should be just `opencode .`.";
  }
  if (label === "Local API base URL") {
    return "The full OpenAI-shaped bridge URL that opencode will call. Change this if your API server runs on another host, machine, or port.";
  }
  if (label === "Local API key") {
    return "A local guard key for this bridge server only. This is not your ChatGPT token or cookie.";
  }
  if (label === "Image output directory") {
    return "Default folder for generated image files when the user does not give an explicit output path.";
  }
  if (label === "Research output directory") {
    return "Default folder for saved Deep Research markdown reports.";
  }
  if (label === "Accounts to use") {
    return "Use account names from secrets/accounts, or `all` when captures exist. Multiple accounts enable failover.";
  }
  return "";
}

function applyPresetDefaults(defaults, preset, discoveredAccounts) {
  const accounts = discoveredAccounts.length ? discoveredAccounts : defaults.accounts;
  if (preset === "agent") {
    return {
      ...defaults,
      accounts,
      account: accounts[0] || defaults.account,
      agentMode: "opencode",
      baseModel: "chatgpt-web/auto",
      limitStrategy: accounts.length > 1 ? "failover" : "auto",
    };
  }
  if (preset === "quick") {
    return {
      ...defaults,
      accounts: accounts.length > 1 ? accounts : defaults.accounts,
      account: accounts[0] || defaults.account,
      agentMode: "optimized",
      baseModel: "chatgpt-web/auto",
      limitStrategy: accounts.length > 1 ? "failover" : "auto",
    };
  }
  return defaults;
}

function printPresetHelp(preset) {
  if (preset === "agent") {
    console.log("Agent preset: fuller opencode prompt, better for coding-agent behavior, heavier prompts.");
    return;
  }
  if (preset === "quick") {
    console.log("Quick preset: optimized bridge prompt, better for small edits and free-account testing.");
    return;
  }
  console.log("Custom preset: keep your own model, prompt mode, and account choices.");
}

function parseAccountSelection(value, discoveredAccounts, fallback) {
  const trimmed = String(value || "").trim();
  if (trimmed.toLowerCase() === "all" && discoveredAccounts.length) {
    return discoveredAccounts;
  }
  const rawItems = splitCsv(trimmed || fallback);
  const selected = rawItems.map((item) => {
    if (/^\d+$/.test(item) && discoveredAccounts.length) {
      return discoveredAccounts[Number(item) - 1] || item;
    }
    return item;
  }).filter(Boolean);
  return Array.from(new Set(selected.length ? selected : splitCsv(fallback)));
}

function modelPolicyForAccounts(accounts) {
  const profiles = accountPlanProfiles(accounts);
  const knownProfiles = profiles.filter((profile) => profile.plan);
  const autoOnly = profiles.length > 0 &&
    knownProfiles.length === profiles.length &&
    profiles.every((profile) => ["free", "go"].includes(profile.plan));
  const plans = profiles.map((profile) => `${profile.name}:${profile.plan || "unknown"}`).join(", ") || "none";
  if (autoOnly) {
    return {
      autoOnly: true,
      profiles,
      reason: `Selected accounts are ${plans}. Free/Go plans are locked to ChatGPT Web Auto because explicit GPT-5.5/Thinking/Pro requests often return model-limit or empty-text responses while the web UI can recover through Auto.`,
    };
  }
  return {
    autoOnly: false,
    profiles,
    reason: profiles.length
      ? `Selected accounts are ${plans}. Explicit model choices stay available; the API will prefer accounts whose plan supports the requested model/effort and then fall back by strategy.`
      : "No account captures were found yet. Explicit model choices stay visible until captures reveal a stricter plan policy.",
  };
}

function accountPlanProfiles(accounts) {
  return accounts.map((name) => accountPlanProfile(name));
}

function accountPlanProfile(name) {
  const capturePath = resolve(projectRoot, "secrets/accounts", name, "chatgpt-request.txt");
  const inferred = inferPlanFromAccountName(name);
  if (!existsSync(capturePath)) {
    return { name, plan: inferred, source: inferred ? "name" : "missing-capture" };
  }
  try {
    const text = readFileSync(capturePath, "utf8");
    const token = extractBearerToken(text);
    const claims = token ? decodeJwtPayload(token) : {};
    const auth = claims?.["https://api.openai.com/auth"];
    const plan = normalizePlan(auth?.chatgpt_plan_type) || inferred;
    return { name, plan, source: plan && auth?.chatgpt_plan_type ? "capture" : inferred ? "name" : "unknown" };
  } catch {
    return { name, plan: inferred, source: inferred ? "name" : "unreadable-capture" };
  }
}

function extractBearerToken(text) {
  const match = text.match(/\bBearer\s+([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?)/i);
  return match?.[1] || "";
}

function decodeJwtPayload(token) {
  const payload = token.split(".")[1];
  if (!payload) {
    return {};
  }
  const normalized = payload.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  return JSON.parse(Buffer.from(padded, "base64").toString("utf8"));
}

function inferPlanFromAccountName(name) {
  const lowered = String(name || "").toLowerCase();
  for (const plan of ["enterprise", "team", "plus", "pro", "go", "free"]) {
    if (lowered.includes(plan)) {
      return plan;
    }
  }
  return "";
}

function normalizePlan(plan) {
  return String(plan || "").trim().toLowerCase();
}

function formatAccountPlanPills(profiles) {
  return profiles.map((profile) => {
    const plan = profile.plan || "unknown";
    const color = ["free", "go"].includes(plan) ? ansi.yellow : plan === "pro" ? ansi.magenta : ansi.cyan;
    return paint(color, `${profile.name}:${plan}`);
  }).join("  ");
}

async function ask(rl, label, defaultValue) {
  const answer = await rl.question(`${label} [${defaultValue}]: `);
  return answer.trim() || defaultValue;
}

async function askChoice(rl, label, defaultValue, choices) {
  for (;;) {
    const answer = (await ask(rl, `${label} (${choices.join("/")})`, defaultValue)).toLowerCase();
    if (choices.includes(answer)) {
      return answer;
    }
    console.log(`Please choose one of: ${choices.join(", ")}`);
  }
}

function buildOpencodeConfig(baseConfig, { apiKey, baseURL, model }) {
  const template = readJsonFile(defaultConfigPath);
  const providerId = model.split("/", 1)[0] || "chatgpt-web";
  const templateProvider = template.provider?.["chatgpt-web"] || {};
  const existingProvider = baseConfig.provider?.[providerId] || {};

  const config = { ...baseConfig };
  config.model = model;
  config.small_model = model;
  config.provider = { ...(baseConfig.provider || {}) };
  config.provider[providerId] = {
    ...templateProvider,
    ...existingProvider,
    name: existingProvider.name || templateProvider.name || "ChatGPT Web Local",
    npm: existingProvider.npm || templateProvider.npm || "@ai-sdk/openai-compatible",
    options: {
      ...(templateProvider.options || {}),
      ...(existingProvider.options || {}),
      baseURL,
      apiKey,
    },
    models: {
      ...(templateProvider.models || {}),
      ...(existingProvider.models || {}),
    },
  };
  config.command = {
    ...(baseConfig.command || {}),
    ...buildChatGPTCommands({ apiKey, baseURL, model }),
  };
  return config;
}

function buildChatGPTCommands({ apiKey, baseURL, model }) {
  const researchModel = applyAgentMode("chatgpt-web/chatgpt-deep-research", agentModeFromModel(model));
  return {
    "chatgpt:usage": {
      template: "/chatgpt:usage",
      description: "Show ChatGPT Web account usage and limits",
      model,
      subtask: false,
    },
    "chatgpt:remain": {
      template: "/chatgpt:remain",
      description: "Alias for ChatGPT Web remaining quotas",
      model,
      subtask: false,
    },
    "chatgpt:research": {
      template: "$ARGUMENTS",
      description: "Run ChatGPT Deep Research",
      model: researchModel,
      subtask: false,
    },
  };
}

function agentModeFromModel(model) {
  const match = String(model || "").match(/[@#]([^/@#]+)$/);
  return match?.[1] || "optimized";
}

function parseArgs(args) {
  const result = {
    account: "",
    accounts: "",
    apiKey: "",
    agentMode: "",
    baseURL: "",
    chatMode: "",
    configPath: "",
    debugConfig: false,
    dryRun: false,
    imageOutputDir: "",
    researchOutputDir: "",
    installConfigPath: "",
    keepConfig: false,
    limitStrategy: "",
    model: "",
    modelFallback: "",
    multiAccount: false,
    passThrough: [],
    project: ".",
    projectSet: false,
    pure: true,
    setup: false,
    apiHost: "",
    apiPort: "",
    statePath: "",
    yes: false,
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "setup" || arg === "--setup") {
      result.setup = true;
      continue;
    }
    if (arg === "--") {
      result.passThrough.push(...args.slice(index + 1));
      break;
    }
    if (arg === "--account") {
      result.account = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--account=")) {
      result.account = arg.slice("--account=".length);
      continue;
    }
    if (arg === "--accounts") {
      result.accounts = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--accounts=")) {
      result.accounts = arg.slice("--accounts=".length);
      continue;
    }
    if (arg === "--api-key") {
      result.apiKey = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--api-key=")) {
      result.apiKey = arg.slice("--api-key=".length);
      continue;
    }
    if (arg === "--agent-mode") {
      result.agentMode = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--agent-mode=")) {
      result.agentMode = arg.slice("--agent-mode=".length);
      continue;
    }
    if (arg === "--base-url") {
      result.baseURL = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--base-url=")) {
      result.baseURL = arg.slice("--base-url=".length);
      continue;
    }
    if (arg === "--host" || arg === "--api-host" || arg === "--server-host") {
      result.apiHost = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--host=")) {
      result.apiHost = arg.slice("--host=".length);
      continue;
    }
    if (arg.startsWith("--api-host=")) {
      result.apiHost = arg.slice("--api-host=".length);
      continue;
    }
    if (arg.startsWith("--server-host=")) {
      result.apiHost = arg.slice("--server-host=".length);
      continue;
    }
    if (arg === "--chat-mode") {
      result.chatMode = normalizeChatMode(args[++index] || "");
      continue;
    }
    if (arg.startsWith("--chat-mode=")) {
      result.chatMode = normalizeChatMode(arg.slice("--chat-mode=".length));
      continue;
    }
    if (arg === "--config") {
      result.configPath = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--config=")) {
      result.configPath = arg.slice("--config=".length);
      continue;
    }
    if (arg === "--debug-config") {
      result.debugConfig = true;
      continue;
    }
    if (arg === "--dry-run") {
      result.dryRun = true;
      continue;
    }
    if (arg === "--image-output-dir") {
      result.imageOutputDir = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--image-output-dir=")) {
      result.imageOutputDir = arg.slice("--image-output-dir=".length);
      continue;
    }
    if (arg === "--research-output-dir") {
      result.researchOutputDir = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--research-output-dir=")) {
      result.researchOutputDir = arg.slice("--research-output-dir=".length);
      continue;
    }
    if (arg === "--install-config") {
      result.installConfigPath = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--install-config=")) {
      result.installConfigPath = arg.slice("--install-config=".length);
      continue;
    }
    if (arg === "--keep-config") {
      result.keepConfig = true;
      continue;
    }
    if (arg === "--limit-strategy") {
      result.limitStrategy = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--limit-strategy=")) {
      result.limitStrategy = arg.slice("--limit-strategy=".length);
      continue;
    }
    if (arg === "--model") {
      result.model = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--model=")) {
      result.model = arg.slice("--model=".length);
      continue;
    }
    if (arg === "--model-fallback") {
      result.modelFallback = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--model-fallback=")) {
      result.modelFallback = arg.slice("--model-fallback=".length);
      continue;
    }
    if (arg === "--port" || arg === "--api-port" || arg === "--server-port") {
      result.apiPort = normalizePort(args[++index] || "");
      continue;
    }
    if (arg.startsWith("--port=")) {
      result.apiPort = normalizePort(arg.slice("--port=".length));
      continue;
    }
    if (arg.startsWith("--api-port=")) {
      result.apiPort = normalizePort(arg.slice("--api-port=".length));
      continue;
    }
    if (arg.startsWith("--server-port=")) {
      result.apiPort = normalizePort(arg.slice("--server-port=".length));
      continue;
    }
    if (arg === "--normal-chat") {
      result.chatMode = "normal";
      continue;
    }
    if (arg === "--temporary-chat") {
      result.chatMode = "temporary";
      continue;
    }
    if (arg === "--multi-account") {
      result.multiAccount = true;
      continue;
    }
    if (arg === "--no-pure") {
      result.pure = false;
      continue;
    }
    if (arg === "--pure") {
      result.pure = true;
      continue;
    }
    if (arg === "--state-path") {
      result.statePath = args[++index] || "";
      continue;
    }
    if (arg.startsWith("--state-path=")) {
      result.statePath = arg.slice("--state-path=".length);
      continue;
    }
    if (arg === "--yes" || arg === "-y") {
      result.yes = true;
      continue;
    }
    if (!arg.startsWith("-") && !result.projectSet) {
      result.project = arg;
      result.projectSet = true;
      continue;
    }
    result.passThrough.push(arg);
  }

  return result;
}

function applyAgentMode(model, mode) {
  if (!mode) {
    return model;
  }
  const slash = model.indexOf("/");
  const modelId = slash === -1 ? model : model.slice(slash + 1);
  if (modelId.includes("@") || modelId.includes("#")) {
    return model;
  }
  return `${model}@${mode}`;
}

function normalizeProviderModel(model) {
  if (model.includes("/")) {
    return model;
  }
  return `chatgpt-web/${model}`;
}

function discoverAccountProfiles() {
  const accountsDir = resolve(projectRoot, "secrets/accounts");
  if (!existsSync(accountsDir)) {
    return [];
  }
  return readdirSync(accountsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

function readJsonFile(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function readJsonIfExists(path) {
  if (!existsSync(path)) {
    return {};
  }
  return readJsonFile(path);
}

function resolveStatePath(explicitPath) {
  if (explicitPath) {
    return resolve(explicitPath);
  }
  if (!existsSync(defaultStatePath) && existsSync(legacyStatePath)) {
    return legacyStatePath;
  }
  return defaultStatePath;
}

function writeJsonWithBackup(path, data) {
  mkdirSync(dirname(path), { recursive: true });
  if (existsSync(path)) {
    copyFileSync(path, `${path}.bak-${timestampSlug()}`);
  }
  writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`);
}

function splitCsv(value) {
  if (!value) {
    return [];
  }
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeChatMode(value) {
  const normalized = String(value || "").trim().toLowerCase().replace("_", "-");
  if (["normal", "regular", "default", "off", "false"].includes(normalized)) {
    return "normal";
  }
  if (["temporary", "incognito", "private", "on", "true"].includes(normalized)) {
    return "temporary";
  }
  return "";
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

function normalizePort(value) {
  const normalized = String(value || "").trim();
  if (!/^\d{1,5}$/.test(normalized)) {
    return defaultApiPort;
  }
  const port = Number(normalized);
  if (port < 1 || port > 65535) {
    return defaultApiPort;
  }
  return normalized;
}

function baseURLForApi(host, port) {
  const connectHost = String(host || defaultApiHost).trim() || defaultApiHost;
  return `http://${connectHost}:${normalizePort(port)}/v1`;
}

function portFromBaseURL(baseURL) {
  try {
    const url = new URL(baseURL);
    if (url.port) {
      return normalizePort(url.port);
    }
    return url.protocol === "https:" ? "443" : "80";
  } catch {
    return defaultApiPort;
  }
}

function serverCommand({ apiKey, accounts, strategy, agentMode, modelFallback, chatMode, imageOutputDir, researchOutputDir, port }) {
  const selectedAccounts = accounts.length ? accounts : ["free"];
  const accountFlags = selectedAccounts.length > 1
    ? `--accounts ${shellQuote(selectedAccounts.join(","))} --account-strategy ${shellQuote(strategy)}`
    : `--account ${shellQuote(selectedAccounts[0])}`;
  const fallbackFlag = modelFallback ? ` --model-fallback ${shellQuote(modelFallback)}` : "";
  const chatModeFlag = chatMode === "normal" ? " --normal-chat" : " --temporary-chat";
  const imageOutputFlag = imageOutputDir ? ` --image-output-dir ${shellQuote(imageOutputDir)}` : "";
  const researchOutputFlag = researchOutputDir ? ` --research-output-dir ${shellQuote(researchOutputDir)}` : "";
  return `CHATGPT_API_KEY=${shellQuote(apiKey)} gpt-bridge serve ${accountFlags} --port ${shellQuote(normalizePort(port))} --agent-mode ${shellQuote(agentMode)}${fallbackFlag}${chatModeFlag}${imageOutputFlag}${researchOutputFlag}`;
}

function timestampSlug() {
  return new Date().toISOString().replaceAll(":", "").replaceAll(".", "");
}
