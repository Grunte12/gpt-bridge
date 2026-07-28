import { tool } from "@opencode-ai/plugin"
import path from "node:path"

const DEFAULT_AGENT_MODEL = "gpt-5-6-sol-high"
const MAX_ERROR_CHARS = 600

function compactError(value: string) {
  const text = value.replace(/\s+/g, " ").trim()
  return text.length > MAX_ERROR_CHARS ? `${text.slice(0, MAX_ERROR_CHARS - 3).trim()}...` : text
}

async function runWorker(args: string[]) {
  let processHandle
  try {
    processHandle = Bun.spawn({
      cmd: ["gpt-bridge", "worker", ...args],
      stdout: "pipe",
      stderr: "pipe",
    })
  } catch (error) {
    throw new Error(`Could not start gpt-bridge: ${String(error)}`)
  }
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(processHandle.stdout).text(),
    new Response(processHandle.stderr).text(),
    processHandle.exited,
  ])
  if (exitCode !== 0) {
    throw new Error(compactError(stderr || stdout || `gpt-bridge exited with ${exitCode}`))
  }
  try {
    return JSON.parse(stdout || "{}")
  } catch {
    throw new Error(`gpt-bridge returned non-JSON output: ${stdout.slice(0, 500)}`)
  }
}

function completionText(payload: unknown) {
  const value = payload as {
    choices?: Array<{ message?: { content?: string } }>
  }
  return value.choices?.[0]?.message?.content || JSON.stringify(payload, null, 2)
}

function outputPath(worktree: string, requested: string) {
  const root = path.resolve(worktree)
  const target = path.resolve(root, requested)
  if (target !== root && !target.startsWith(`${root}${path.sep}`)) {
    throw new Error("outputPath must stay inside the OpenCode worktree")
  }
  return target
}

export const doctor = tool({
  description: "Check the one-account GPT Bridge direct runtime and its captured ChatGPT Web models; no daemon is required.",
  args: {},
  async execute() {
    const payload = await runWorker(["doctor", "--json"])
    return JSON.stringify(payload, null, 2)
  },
})

export const chat = tool({
  description: "Send one direct ChatGPT Web request; defaults to verified GPT-5.6 Sol high.",
  args: {
    message: tool.schema.string().describe("Message to send"),
    model: tool.schema.string().optional().describe(`Bridge model alias; defaults to ${DEFAULT_AGENT_MODEL}`),
    system: tool.schema.string().optional().describe("Optional system instruction"),
  },
  async execute(args) {
    const command = [
      "chat",
      "--message",
      args.message,
      "--model",
      args.model || DEFAULT_AGENT_MODEL,
      "--json",
    ]
    if (args.system) command.push("--system", args.system)
    const payload = await runWorker(command)
    return completionText(payload)
  },
})

export const research = tool({
  description: "Run Deep Research directly through the captured ChatGPT account; no daemon is required.",
  args: {
    prompt: tool.schema.string().describe("Research question with scope and source requirements"),
  },
  async execute(args) {
    const payload = await runWorker(["research", "--prompt", args.prompt, "--json"])
    return JSON.stringify(payload, null, 2)
  },
})

export const image = tool({
  description: "Generate a ChatGPT Image with compact output; repeat calls as needed for quality.",
  args: {
    prompt: tool.schema.string().describe(
      "Give a self-contained labeled artifact spec: deliverable/use; canvas/composition; content/relationships; visual direction; exact quoted text; constraints. The installed gpt-bridge-worker skill provides mode and risk guides.",
    ),
    outputPath: tool.schema.string().optional().describe(
      "Optional image path relative to the OpenCode worktree; reuse one draft path to keep iteration compact",
    ),
    transparent: tool.schema.boolean().optional().describe(
      "Return a frontend-ready PNG with verified alpha; requires outputPath ending in .png",
    ),
  },
  async execute(args, context) {
    const command = ["image", "--prompt", args.prompt, "--brief"]
    if (args.outputPath) command.push("--output-path", outputPath(context.worktree, args.outputPath))
    if (args.transparent) {
      if (!args.outputPath) throw new Error("transparent image generation requires outputPath")
      command.push("--transparent")
    }
    const payload = await runWorker(command)
    return JSON.stringify(payload)
  },
})

export const image_edit = tool({
  description: "Edit, restyle, localize, or composite up to 10 source images with compact output.",
  args: {
    prompt: tool.schema.string().describe(
      "State source roles, the requested change, exact preservation invariants, exact quoted text, and forbidden changes",
    ),
    inputPaths: tool.schema.array(tool.schema.string()).min(1).max(10).describe(
      "Source image paths relative to the OpenCode worktree, in the order referenced by the prompt",
    ),
    outputPath: tool.schema.string().describe(
      "Edited image path relative to the OpenCode worktree; reuse one draft path during refinement",
    ),
    aspectRatio: tool.schema.enum(["auto", "1:1", "3:4", "9:16", "4:3", "16:9"]).optional(),
    transparent: tool.schema.boolean().optional().describe(
      "Return a frontend-ready PNG with verified alpha; outputPath must end in .png",
    ),
  },
  async execute(args, context) {
    const command = [
      "edit",
      "--prompt",
      args.prompt,
      "--aspect-ratio",
      args.aspectRatio || "auto",
      "--output-path",
      outputPath(context.worktree, args.outputPath),
      "--brief",
    ]
    for (const inputPath of args.inputPaths) {
      command.push("--input-image", outputPath(context.worktree, inputPath))
    }
    if (args.transparent) command.push("--transparent")
    const payload = await runWorker(command)
    return JSON.stringify(payload)
  },
})

export const report = tool({
  description: "Create a standalone HTML report directly with verified GPT-5.6 Sol high.",
  args: {
    prompt: tool.schema.string().describe("Report topic, evidence, and visualization requirements"),
    outputPath: tool.schema.string().describe("HTML path relative to the OpenCode worktree"),
    title: tool.schema.string().optional().describe("Optional reader-facing title"),
  },
  async execute(args, context) {
    const target = outputPath(context.worktree, args.outputPath)
    const command = [
      "report",
      "--prompt",
      args.prompt,
      "--model",
      DEFAULT_AGENT_MODEL,
      "--out",
      target,
      "--json",
    ]
    if (args.title) command.push("--title", args.title)
    const payload = await runWorker(command)
    return JSON.stringify(payload, null, 2)
  },
})
