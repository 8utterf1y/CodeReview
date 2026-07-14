import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Validate that the dispatched subagent advanced the expected SpecDiff state transition.",
  args: {
    requirementId: tool.schema.string().min(1),
    action: tool.schema.enum(["frame_obligations", "investigate", "review"]),
    actionId: tool.schema.string().optional(),
  },
  async execute(args, context) {
    const workspace = join(context.directory, ".specdiff", "audit");
    const dir = join(workspace, ".submissions");
    await mkdir(dir, { recursive: true });
    const path = join(dir, `${randomUUID()}.json`);
    await writeFile(path, JSON.stringify({ requirement_id: args.requirementId, action: args.action, action_id: args.actionId }), "utf8");
    return run(["audit-dispatch-result", "--workspace", workspace, "--payload", path]);
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
