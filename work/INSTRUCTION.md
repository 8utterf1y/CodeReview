# SpecDiff Competition Entry

## 1. Environment Setup

This entry uses the bundled Python implementation under `work/specdiff`. No package installation, build step,
or manual interaction is required for the default CLI path.

Required runtime:

```bash
python3 --version
```

Python 3.9 or newer is recommended.

Optional self-check:

```bash
python3 self_check.py
```

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

- `--repo`: local repository path for the implementation under review.
- `--docs`: design/specification document. It may contain explicit obligations or an RFC inventory.
- `--out`: JSON result file path.
- `--report`: optional Markdown report path.

When `--docs` is an RFC inventory, SpecDiff treats the RFC text as a specification corpus, builds bounded
Requirement Packs, and audits those packs. RFC manifest rows are not treated as implementation requirements.

## 3. Completion Criteria

Execution is complete when the command exits. A successful run exits with code `0` and writes the JSON result
file specified by `--out`. Invalid input paths or unreadable documents cause a non-zero exit with an error
message.

## 4. Result Retrieval

The primary machine-readable output is:

```text
/app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work/result/issues.json
```

The optional human-readable report is:

```text
/app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work/result/report.md
```

Each issue includes specification evidence, code evidence when available, match type, severity, confidence, and
verification notes.

## 5. Included Skill

The entry also includes an OpenCode skill at:

```text
work/skills/spec-code-consistency/SKILL.md
```

The CLI is the authoritative execution path for automatic judging. The OpenCode skill documents the controlled
agent workflow for interactive use.
