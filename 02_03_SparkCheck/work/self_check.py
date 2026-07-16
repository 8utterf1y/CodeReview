from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


REQUIRED_PATHS = [
    "INSTRUCTION.md",
    ".opencode/commands/spec-audit.md",
    ".opencode/agents/spec-compliance-orchestrator.md",
    ".opencode/agents/code-investigator.md",
    ".opencode/tools/audit_start.ts",
    ".opencode/tools/audit_next.ts",
    ".opencode/tools/code_search.ts",
    ".opencode/tools/submit_batch_results.ts",
    "skills/spec-code-consistency/SKILL.md",
    "specdiff/tool_api.py",
    "specdiff/audit_runtime.py",
    "specdiff/rfc_prepare.py",
]


def main() -> int:
    missing = [item for item in REQUIRED_PATHS if not (ROOT / item).exists()]
    if missing:
        sys.stderr.write("missing required files:\n")
        for item in missing:
            sys.stderr.write(f"  - {item}\n")
        return 1

    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}{os.pathsep}{existing}"

    checks = [
        [sys.executable, "-m", "specdiff.tool_api", "--help"],
    ]
    for cmd in checks:
        result = subprocess.run(cmd, cwd=str(ROOT), env=env, text=True, capture_output=True)
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode

    print("self-check passed: required files present and runtime imports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
