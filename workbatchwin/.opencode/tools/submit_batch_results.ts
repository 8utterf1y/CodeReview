import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Submit results for multiple Requirement Packs in the active audit batch.",
  args: {
    batchId: tool.schema.string().min(1),
    results: tool.schema.array(tool.schema.object({
      requirementId: tool.schema.string().min(1),
      status: tool.schema.enum(["covered", "partial", "violated", "unknown"]),
      summary: tool.schema.string().min(1),
      specClauseIds: tool.schema.array(tool.schema.string()).optional(),
      evidenceIds: tool.schema.array(tool.schema.string()),
      confidence: tool.schema.number().min(0).max(1),
      issue: tool.schema.object({
        title: tool.schema.string().optional(),
        severity: tool.schema.enum(["critical", "high", "medium", "low"]).optional(),
      }).optional(),
    })),
  },
  async execute(args, context) {
    const payload = {
      batch_id: args.batchId,
      results: args.results.map((item) => {
        const result = {
          requirement_id: item.requirementId,
          status: item.status,
          summary: item.summary,
          evidence_ids: item.evidenceIds,
          confidence: item.confidence,
          issue: item.issue,
        };
        return item.specClauseIds === undefined ? result : { ...result, spec_clause_ids: item.specClauseIds };
      }),
    };
    const workspace = join(context.directory, ".specdiff", "audit");
    const dir = join(workspace, ".submissions");
    await mkdir(dir, { recursive: true });
    const path = join(dir, `${randomUUID()}.json`);
    await writeFile(path, JSON.stringify(payload), "utf8");
    return run(["audit-submit-batch-results", "--workspace", workspace, "--payload", path]);
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
