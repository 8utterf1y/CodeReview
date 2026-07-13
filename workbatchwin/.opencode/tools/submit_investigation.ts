import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { delimiter, join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Deprecated legacy investigation submission. Current agents must use frame_obligations followed by submit_conclusion.",
  args: {
    requirementId: tool.schema.string(),
    conclusion: tool.schema.enum(["satisfied", "mismatch", "uncertain"]),
    summary: tool.schema.string().min(1),
    evidenceIds: tool.schema.array(tool.schema.string()),
    uncertainties: tool.schema.array(tool.schema.string()),
    obligations: tool.schema.array(tool.schema.object({
      id: tool.schema.string(),
      description: tool.schema.string(),
      sourceClauseIds: tool.schema.array(tool.schema.string()),
    })).optional(),
    findings: tool.schema.array(tool.schema.object({
      obligationId: tool.schema.string(),
      status: tool.schema.enum(["supported", "contradicted", "partial", "not_found"]),
      evidenceIds: tool.schema.array(tool.schema.string()),
    })).optional(),
    negativeChecks: tool.schema.array(tool.schema.object({
      dimension: tool.schema.string(),
      status: tool.schema.enum(["searched", "not_applicable", "inconclusive"]),
      result: tool.schema.string(),
    })).optional(),
    mismatchKind: tool.schema.enum(["missing", "partial", "contradiction"]).optional(),
    title: tool.schema.string().optional(),
    severity: tool.schema.enum(["critical", "high", "medium", "low"]).optional(),
    confidence: tool.schema.number().min(0).max(1).optional(),
  },
  async execute(args, context) {
    const payload = {
      requirement_id: args.requirementId, conclusion: args.conclusion, summary: args.summary,
      evidence_ids: args.evidenceIds, uncertainties: args.uncertainties,
      obligations: (args.obligations || []).map((item) => ({
        id: item.id,
        description: item.description,
        source_clause_ids: item.sourceClauseIds,
      })),
      findings: (args.findings || []).map((item) => ({
        obligation_id: item.obligationId,
        status: item.status,
        evidence_ids: item.evidenceIds,
      })),
      negative_checks: args.negativeChecks || [],
      mismatch_kind: args.mismatchKind, title: args.title, severity: args.severity,
      confidence: args.confidence,
    };
    const workspace = join(context.directory, ".specdiff", "audit");
    return submit(workspace, "audit-submit-simple-investigation", payload);
  },
});

async function submit(workspace: string, command: string, payload: object) {
  const dir = join(workspace, ".submissions");
  await mkdir(dir, { recursive: true });
  const path = join(dir, `${randomUUID()}.json`);
  await writeFile(path, JSON.stringify(payload), "utf8");
  const homeDir = process.env.HOME || process.env.USERPROFILE;
  const runtime = [process.env.SPECDIFF_RUNTIME, `${process.cwd()}/.opencode/specdiff-runtime`, homeDir ? `${homeDir}/.config/opencode/specdiff-runtime` : undefined, process.env.PYTHONPATH].filter(Boolean).join(delimiter);
  try {
    const { stdout } = await execFileAsync(pythonBin(), ["-m", "specdiff.tool_api", command, "--workspace", workspace, "--payload", path], { cwd: process.cwd(), env: { ...process.env, PYTHONPATH: runtime }, maxBuffer: 50 * 1024 * 1024 });
    return stdout;
  } catch (error) {
    const err = error as Error & { stderr?: string; stdout?: string };
    throw new Error(err.stderr || err.stdout || err.message);
  }
}

function pythonBin() {
  return process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
}
