import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Search indexed code for one requirement. Repository, role, query IDs, and evidence IDs are automatic.",
  args: {
    requirementId: tool.schema.string().min(1),
    operation: tool.schema.enum(["text", "symbol", "references", "callers", "callees", "source", "repo_map", "component", "build"]),
    term: tool.schema.string().optional(),
    path: tool.schema.string().optional(),
    line: tool.schema.number().int().positive().optional(),
    window: tool.schema.number().int().positive().max(100).optional(),
  },
  async execute(args, context) {
    const workspace = join(context.directory, ".specdiff", "audit");
    const mode = args.operation === "text" ? "concept" : args.operation;
    const command = ["audit-query", "--workspace", workspace, "--requirement-id", args.requirementId, "--role", "investigator", "--mode", mode];
    if (args.term) command.push("--query", args.term);
    if (args.path) command.push("--path", args.path);
    if (args.line !== undefined) {
      const window = args.window ?? 20;
      command.push("--start", String(Math.max(1, args.line - window)), "--end", String(args.line + window));
    }
    return run(command);
  },
});

async function run(args: string[]) {
  const homeDir = process.env.USERPROFILE;
  const runtime = [process.env.SPECDIFF_RUNTIME, `${process.cwd()}/.opencode/specdiff-runtime`, homeDir ? join(homeDir, ".config", "opencode", "specdiff-runtime") : undefined, process.env.PYTHONPATH].filter(Boolean).join(";");
  const { stdout } = await execFileAsync(pythonBin(), ["-m", "specdiff.tool_api", ...args], { env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
  return stdout;
}

function pythonBin() {
  return "python";
}
