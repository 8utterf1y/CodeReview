import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Submit one lightweight evidence review. No repository search or internal IDs are required.",
  args: {
    requirementId: tool.schema.string().min(1),
    verdict: tool.schema.enum(["accept", "reject", "uncertain"]),
    reason: tool.schema.string().min(1),
    unsupportedClaims: tool.schema.array(tool.schema.string()),
  },
  async execute(args, context) {
    const workspace = join(context.directory, ".specdiff", "audit");
    const dir = join(workspace, ".submissions");
    await mkdir(dir, { recursive: true });
    const path = join(dir, `${randomUUID()}.json`);
    await writeFile(path, JSON.stringify({ requirement_id: args.requirementId, verdict: args.verdict, reason: args.reason, unsupported_claims: args.unsupportedClaims }), "utf8");
    return run(["audit-submit-simple-review", "--workspace", workspace, "--payload", path], context.directory);
  },
});

async function run(args: string[], projectRoot: string) {  const runtime = [join(projectRoot, ".opencode", "specdiff-runtime"), process.env.PYTHONPATH].filter(Boolean).join(";");
  const { stdout } = await execFileAsync(pythonBin(), ["-m", "specdiff.tool_api", ...args], { env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
  return stdout;
}

function pythonBin() {
  return "python";
}
