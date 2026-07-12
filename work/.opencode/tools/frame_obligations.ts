import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Frame implementation obligations for the current Requirement Pack before code investigation.",
  args: {
    requirementId: tool.schema.string().min(1),
    obligations: tool.schema.array(tool.schema.object({
      description: tool.schema.string().min(1),
      sourceClauseIds: tool.schema.array(tool.schema.string()),
    })),
  },
  async execute(args, context) {
    const payload = {
      requirement_id: args.requirementId,
      obligations: args.obligations.map((item) => ({
        description: item.description,
        source_clause_ids: item.sourceClauseIds,
      })),
    };
    const workspace = join(context.directory, ".specdiff", "audit");
    return submit(workspace, "audit-frame-obligations", payload);
  },
});

async function submit(workspace: string, command: string, payload: object) {
  const dir = join(workspace, ".submissions");
  await mkdir(dir, { recursive: true });
  const path = join(dir, `${randomUUID()}.json`);
  await writeFile(path, JSON.stringify(payload), "utf8");
  const runtime = [process.env.SPECDIFF_RUNTIME, `${process.cwd()}/.opencode/specdiff-runtime`, process.env.HOME ? `${process.env.HOME}/.config/opencode/specdiff-runtime` : undefined, process.env.PYTHONPATH].filter(Boolean).join(":");
  try {
    const { stdout } = await execFileAsync("python3", ["-m", "specdiff.tool_api", command, "--workspace", workspace, "--payload", path], { cwd: process.cwd(), env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
    return stdout;
  } catch (error) {
    const err = error as Error & { stderr?: string; stdout?: string };
    throw new Error(err.stderr || err.stdout || err.message);
  }
}
