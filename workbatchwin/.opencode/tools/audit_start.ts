import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Start a controlled audit from a design document or RFC inventory in the current repository.",
  args: {
    repo: tool.schema.string().min(1).describe("Repository path to audit."),
    docs: tool.schema.string().min(1).describe("Design/specification file or RFC inventory."),
    out: tool.schema.string().min(1).describe("Final issues.json path."),
  },
  async execute(args, context) {
    const projectRoot = resolve(context.directory);
    const repo = resolve(projectRoot, args.repo);
    const workspace = join(projectRoot, ".specdiff", "audit");
    const docsSource = resolve(projectRoot, args.docs);
    const out = isAbsolute(args.out) ? resolve(args.out) : resolve(repo, args.out);
    await mkdir(workspace, { recursive: true });
    let parsed = await run(["extract-requirements", "--docs", docsSource], projectRoot);
    let payload = JSON.parse(parsed);
    let lockedInput = join(workspace, "parsed-requirements.json");
    if (!Array.isArray(payload.requirements) || payload.requirements.length === 0) {
      lockedInput = join(workspace, "spec", "rfc-corpus.json");
      await mkdir(join(workspace, "spec"), { recursive: true });
      await run([
        "prepare-rfcs",
        "--inventory", docsSource,
        "--out", lockedInput,
        "--cache-dir", join(workspace, "spec", "rfc-cache"),
      ], projectRoot);
      parsed = await readFile(lockedInput, "utf8");
      payload = JSON.parse(parsed);
      if (!Array.isArray(payload.requirement_packs) || payload.requirement_packs.length === 0) {
        throw new Error(`No explicit requirements or RFC requirement packs were produced from: ${docsSource}`);
      }
    }
    await writeFile(lockedInput, parsed, "utf8");
    await run(["audit-init", "--repo", repo, "--requirements", lockedInput, "--workspace", workspace, "--out", out], projectRoot);
    return run(["audit-next", "--workspace", workspace], projectRoot);
  },
});

async function run(args: string[], projectRoot: string) {
  const { stdout } = await execFileAsync(pythonBin(), ["-m", "specdiff.tool_api", ...args], {
    env: runtimeEnv(projectRoot), maxBuffer: 50 * 1024 * 1024,
  });
  return stdout;
}

function runtimeEnv(projectRoot: string) {  const runtime = [join(projectRoot, ".opencode", "specdiff-runtime"), process.env.PYTHONPATH].filter(Boolean).join(";");
  return { ...process.env, PYTHONPATH: runtime };
}

function pythonBin() {
  return "python";
}
