import { tool } from "@opencode-ai/plugin";
import { execFile } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { delimiter, join, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export default tool({
  description: "Start a controlled audit from a design document or RFC inventory in the current repository.",
  args: {
    docs: tool.schema.string().min(1).describe("Design/specification file or RFC inventory."),
    out: tool.schema.string().min(1).describe("Final issues.json path."),
  },
  async execute(args, context) {
    const repo = resolve(context.directory);
    const workspace = join(repo, ".specdiff", "audit");
    const docsSource = resolve(repo, args.docs);
    const out = resolve(repo, args.out);
    await mkdir(workspace, { recursive: true });
    let parsed = await run(["extract-requirements", "--docs", docsSource]);
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
      ]);
      parsed = await readFile(lockedInput, "utf8");
      payload = JSON.parse(parsed);
      if (!Array.isArray(payload.requirement_packs) || payload.requirement_packs.length === 0) {
        throw new Error(`No explicit requirements or RFC requirement packs were produced from: ${docsSource}`);
      }
    }
    await writeFile(lockedInput, parsed, "utf8");
    await run(["audit-init", "--repo", repo, "--requirements", lockedInput, "--workspace", workspace, "--out", out]);
    return run(["audit-next", "--workspace", workspace]);
  },
});

async function run(args: string[]) {
  const { stdout } = await execFileAsync(pythonBin(), ["-m", "specdiff.tool_api", ...args], {
    env: runtimeEnv(), maxBuffer: 50 * 1024 * 1024,
  });
  return stdout;
}

function runtimeEnv() {
  const homeDir = process.env.HOME || process.env.USERPROFILE;
  const runtime = [process.env.SPECDIFF_RUNTIME, `${process.cwd()}/.opencode/specdiff-runtime`, homeDir ? `${homeDir}/.config/opencode/specdiff-runtime` : undefined, process.env.PYTHONPATH].filter(Boolean).join(delimiter);
  return { ...process.env, PYTHONPATH: runtime };
}

function pythonBin() {
  return process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
}
