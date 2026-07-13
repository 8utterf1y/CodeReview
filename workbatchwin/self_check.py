from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SELF_CHECK_DIR = Path(tempfile.gettempdir()) / "specdiff-self-check"
OUT = SELF_CHECK_DIR / "issues.json"
REPORT = SELF_CHECK_DIR / "report.md"


def main() -> int:
    SELF_CHECK_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "specdiff",
        "--repo",
        str(ROOT / "testdata" / "repo"),
        "--docs",
        str(ROOT / "testdata" / "docs" / "benchmark.md"),
        "--out",
        str(OUT),
        "--report",
        str(REPORT),
    ]
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode

    payload = json.loads(OUT.read_text(encoding="utf-8"))
    issues = payload.get("issues", [])
    required_keys = {
        "id",
        "title",
        "match_type",
        "severity",
        "confidence",
        "description",
        "spec_evidence",
        "code_evidence",
        "verification",
    }
    if len(issues) < 4:
        sys.stderr.write(f"expected at least 4 smoke-test issues, got {len(issues)}\n")
        return 1
    for issue in issues:
        missing = sorted(required_keys - set(issue))
        if missing:
            sys.stderr.write(f"issue {issue.get('id')} missing keys: {missing}\n")
            return 1
        if not issue["spec_evidence"] or not issue["code_evidence"]:
            sys.stderr.write(f"issue {issue.get('id')} lacks evidence\n")
            return 1

    print(f"self-check passed: {len(issues)} issues, output={OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
