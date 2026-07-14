import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Submit the final conclusion for already-framed obligations.",
  args: {
    requirementId: tool.schema.string().min(1),
    conclusion: tool.schema.enum(["satisfied", "mismatch", "uncertain"]),
    summary: tool.schema.string().min(1),
    obligationResults: tool.schema.array(tool.schema.object({
      obligationId: tool.schema.string().min(1),
      status: tool.schema.enum(["supported", "contradicted", "partial", "not_found"]),
      evidenceIds: tool.schema.array(tool.schema.string()),
    })),
    negativeChecks: tool.schema.array(tool.schema.object({
      dimension: tool.schema.string().min(1),
      status: tool.schema.enum(["searched", "not_applicable", "inconclusive"]),
      queryIds: tool.schema.array(tool.schema.string()).optional(),
      result: tool.schema.string().min(1),
    })).optional(),
    uncertainties: tool.schema.array(tool.schema.string()),
    mismatchKind: tool.schema.enum(["missing", "partial", "contradiction"]).optional(),
    title: tool.schema.string().optional(),
    severity: tool.schema.enum(["critical", "high", "medium", "low"]).optional(),
    confidence: tool.schema.number().min(0).max(1).optional(),
  },
  async execute(args, context) {
    const payload = {
      requirement_id: args.requirementId,
      conclusion: args.conclusion,
      summary: args.summary,
      obligation_results: args.obligationResults.map((item) => ({
        obligation_id: item.obligationId,
        status: item.status,
        evidence_ids: item.evidenceIds,
      })),
      negative_checks: (args.negativeChecks || []).map((item) => ({
        dimension: item.dimension,
        status: item.status,
        query_ids: item.queryIds || [],
        result: item.result,
      })),
      uncertainties: args.uncertainties,
      mismatch_kind: args.mismatchKind,
      title: args.title,
      severity: args.severity,
      confidence: args.confidence,
    };
    const workspace = join(context.directory, ".specdiff", "audit");
    return submit(workspace, "audit-submit-conclusion", payload);
  },
});

async function submit(workspace: string, command: string, payload: object) {
  const dir = join(workspace, ".submissions");
  await mkdir(dir, { recursive: true });
  const path = join(dir, `${randomUUID()}.json`);
  await writeFile(path, JSON.stringify(payload), "utf8");
  const homeDir = process.env.USERPROFILE;
  const runtime = [process.env.SPECDIFF_RUNTIME, `${process.cwd()}/.opencode/specdiff-runtime`, homeDir ? join(homeDir, ".config", "opencode", "specdiff-runtime") : undefined, process.env.PYTHONPATH].filter(Boolean).join(";");
  try {
    const { stdout } = await execFileAsync(pythonBin(), ["-m", "specdiff.tool_api", command, "--workspace", workspace, "--payload", path], { cwd: process.cwd(), env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
    return stdout;
  } catch (error) {
    const err = error as Error & { stderr?: string; stdout?: string };
    throw new Error(err.stderr || err.stdout || err.message);
  }
}

function pythonBin() {
  return "python";
}
