import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { join, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Compile an RFC inventory into cached, source-linked candidate requirement JSON using RFC Editor text.",
  args: {
    inventory: tool.schema.string().min(1).describe("Markdown inventory containing RFC references."),
    out: tool.schema.string().min(1).describe("Candidate requirements JSON path."),
    maxPerRfc: tool.schema.number().int().positive().optional().describe("Optional cap for exploratory runs; omit for complete output."),
    offline: tool.schema.boolean().optional().describe("Use only RFCs already present in the local cache."),
  },
  async execute(args, context) {
    const repo = resolve(context.directory);
    const inventory = resolve(repo, args.inventory);
    const out = resolve(repo, args.out);
    const cache = join(repo, ".specdiff", "rfc-cache");
    const command = ["-m", "specdiff.tool_api", "prepare-rfcs", "--inventory", inventory, "--out", out, "--cache-dir", cache];
    if (args.maxPerRfc !== undefined) command.push("--max-per-rfc", String(args.maxPerRfc));
    if (args.offline) command.push("--offline");
    const runtime = [process.env.SPECDIFF_RUNTIME, `${process.cwd()}/.opencode/specdiff-runtime`, process.env.HOME ? `${process.env.HOME}/.config/opencode/specdiff-runtime` : undefined, process.env.PYTHONPATH].filter(Boolean).join(":");
    try {
      const { stdout } = await execFileAsync("python3", command, { cwd: repo, env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
      return stdout;
    } catch (error) {
      const err = error as Error & { stderr?: string; stdout?: string };
      throw new Error(err.stderr || err.stdout || err.message);
    }
  },
});
