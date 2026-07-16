import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Return exactly one next workflow action with its complete Agent input packet.",
  args: {},
  async execute(_args, context) {
    const workspace = join(context.directory, ".specdiff", "audit");
    try {
      return await run(["audit-next", "--workspace", workspace], context.directory);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return JSON.stringify({ next_action: "blocked", reason: `No runnable audit state: ${message}` });
    }
  },
});

async function run(args: string[], projectRoot: string) {  const runtime = [join(projectRoot, ".opencode", "specdiff-runtime"), process.env.PYTHONPATH].filter(Boolean).join(";");
  const { stdout } = await execFileAsync(pythonBin(), ["-m", "specdiff.tool_api", ...args], { env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
  return stdout;
}

function pythonBin() {
  return "python";
}
