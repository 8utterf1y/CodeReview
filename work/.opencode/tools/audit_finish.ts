import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { delimiter, join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Assemble the final JSON and SARIF after the state machine reports finish.",
  args: {},
  async execute(_args, context) {
    const workspace = join(context.directory, ".specdiff", "audit");
    const homeDir = process.env.HOME || process.env.USERPROFILE;
  const runtime = [process.env.SPECDIFF_RUNTIME, `${process.cwd()}/.opencode/specdiff-runtime`, homeDir ? `${homeDir}/.config/opencode/specdiff-runtime` : undefined, process.env.PYTHONPATH].filter(Boolean).join(delimiter);
    const { stdout } = await execFileAsync(pythonBin(), ["-m", "specdiff.tool_api", "audit-finish", "--workspace", workspace], { env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
    return stdout;
  },
});

function pythonBin() {
  return process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
}
