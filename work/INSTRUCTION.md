# SpecDiff Competition Entry

## 1. Environment Setup

This entry is intended to run through OpenCode with the bundled SpecDiff tools and skill. The Python runtime
under `work/specdiff` is used by those OpenCode tools to build Code Facts, compile RFC inventories into
Requirement Packs, control workflow state, and assemble the final result.

Required runtime:

```bash
python3 --version
```

Python 3.9 or newer is recommended.

Optional self-check:

```bash
python3 self_check.py
```

## 2. OpenCode Execution Flow

Install the OpenCode integration into the repository under audit:

```bash
cd /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work
python3 install_opencode_interactive.py \
  --target /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack \
  --force
```

Start OpenCode from the target repository:

```bash
cd /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack
opencode
```

Run the audit:

```text
/spec-audit /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/Difference/benchmark.md \
  /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work/result/issues.json
```

The first argument is the design/specification document. It may contain explicit obligations or an RFC inventory.
When it is an RFC inventory, SpecDiff internally builds an RFC corpus and bounded Requirement Packs. RFC manifest
rows are not treated as implementation requirements.

## 3. Completion Criteria

Execution is complete when `audit_finish` succeeds and writes the requested JSON result. Invalid input paths,
unreadable documents, or an empty audit state are reported by the OpenCode tool chain.

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

OpenCode is the authoritative workflow path for this entry. The legacy `python3 -m specdiff` CLI remains in the
repository as an auxiliary scanner, but it is not the controlled Requirement Pack workflow.
