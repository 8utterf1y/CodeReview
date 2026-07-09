# SpecDiff Competition Entry

## 1. Environment Setup

This entry uses only Python standard-library modules. No network access, package installation, build step, or manual interaction is required.

Required runtime:

```bash
python3 --version
```

Python 3.9 or newer is recommended.

Optional self-check:

```bash
python3 self_check.py
```

The self-check runs the detector against a tiny bundled fixture and validates that JSON output contains evidence-backed issues. It is not required for judging the benchmark.

## 2. Execution Flow

Run the detector from the submitted `work/` directory:

```bash
python3 -m specdiff \
  --repo /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack \
  --docs /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/Difference/benchmark.md \
  --out /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work/result/issues.json \
  --report /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work/result/report.md
```

Input parameters:

- `--repo`: local git repository path for the implementation under review.
- `--docs`: design document path. This may be a single Markdown/text file or a directory containing Markdown/text files.
- `--out`: JSON result file path.
- `--report`: optional Markdown report path.

The benchmark repository is expected to be the F-Stack repository at commit `58cc9cf685f496d0542b072fe3e6246d3ceba781` on branch `competition`, but the tool does not require the branch name to run.

## 3. Completion Criteria

Execution is complete when the command exits. A successful run exits with code `0` and writes the JSON result file specified by `--out`.

If the repository or document path is missing, the command exits non-zero with an error message.

## 4. Result Retrieval

The primary machine-readable output is:

```text
/app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work/result/issues.json
```

The optional human-readable report is:

```text
/app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work/result/report.md
```

The JSON result has this shape:

```json
{
  "tool": "specdiff",
  "issues": [
    {
      "id": "ISSUE-001",
      "title": "Implementation limits Neighbor Discovery options",
      "match_type": "code_weaker_than_spec",
      "severity": "HIGH",
      "confidence": 0.91,
      "description": "...",
      "spec_evidence": {
        "document": "RFC 4861",
        "section": "6.3.4 / 4.6.2",
        "quote": "..."
      },
      "code_evidence": {
        "file": "freebsd/netinet6/nd6.c",
        "line": 105,
        "quote": "..."
      },
      "verification": [
        "..."
      ]
    }
  ]
}
```

Each issue includes:

- inconsistency description
- design/spec evidence
- code evidence with file path and line number when available
- match type
- severity and confidence
- verification notes suitable for automatic or manual review

## 5. Included Skill

The entry also includes a Codex/Claude-style skill at:

```text
work/skills/spec-code-consistency/SKILL.md
```

The CLI is the authoritative execution path for automatic judging. The skill documents the audit workflow and can be used by an agent to extend or manually validate findings.
