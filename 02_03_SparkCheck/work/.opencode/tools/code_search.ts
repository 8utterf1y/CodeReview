import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Search indexed code for an active batch or one requirement. Use text/symbol/reference operations for discovery, then use operation=source to create exact source-span evidence before submitting covered/partial/code-backed violated results. Query IDs and evidence IDs are automatic.",
  args: {
    requirementId: tool.schema.string().min(1).optional(),
    operation: tool.schema.enum(["text", "symbol", "references", "callers", "callees", "source", "repo_map", "component", "build"]),
    term: tool.schema.string().optional(),
    path: tool.schema.string().optional(),
    line: tool.schema.number().int().positive().optional(),
    window: tool.schema.number().int().positive().max(100).optional(),
    startLine: tool.schema.number().int().positive().optional(),
    endLine: tool.schema.number().int().positive().optional(),
  },
  async execute(args, context) {
    const workspace = join(context.directory, ".specdiff", "audit");
    const mode = args.operation === "text" ? "concept" : args.operation;
    const command = ["audit-query", "--workspace", workspace, "--role", "investigator", "--mode", mode];
    if (args.requirementId) command.push("--requirement-id", args.requirementId);
    if (args.term) command.push("--query", args.term);
    if (args.path) command.push("--path", args.path);
    if (args.startLine !== undefined || args.endLine !== undefined) {
      if (args.startLine === undefined || args.endLine === undefined) throw new Error("source search requires both startLine and endLine");
      command.push("--start", String(args.startLine), "--end", String(args.endLine));
    } else if (args.line !== undefined) {
      const window = args.window ?? 20;
      command.push("--start", String(Math.max(1, args.line - window)), "--end", String(args.line + window));
    }
    return run(command, context.directory);
  },
});

async function run(args: string[], projectRoot: string) {
  const runtime = [join(projectRoot, ".opencode", "specdiff-runtime"), process.env.PYTHONPATH].filter(Boolean).join(";");
  const { stdout } = await execFileAsync("python", ["-m", "specdiff.tool_api", ...args], { env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
  return stdout;
}
