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
      return await run(["audit-next", "--workspace", workspace]);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return JSON.stringify({ next_action: "blocked", reason: `No runnable audit state: ${message}` });
    }
  },
});

async function run(args: string[]) {
  const runtime = [process.env.SPECDIFF_RUNTIME, `${process.cwd()}/.opencode/specdiff-runtime`, process.env.HOME ? `${process.env.HOME}/.config/opencode/specdiff-runtime` : undefined, process.env.PYTHONPATH].filter(Boolean).join(":");
  const { stdout } = await execFileAsync("python3", ["-m", "specdiff.tool_api", ...args], { env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
  return stdout;
}
