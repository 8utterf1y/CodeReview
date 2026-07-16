# OpenCode Integration

This directory contains the OpenCode command, agents, tools, skill, and bundled SpecDiff runtime.

## Windows Usage

Start OpenCode from the submitted `work/` directory:

```powershell
cd C:\judge-assets\01_03_ai_implementation_design_difference_detection\work
opencode
```

Run the audit by passing the repository path, specification path, and output path:

```text
/spec-audit C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack\.specdiff\issues.json
```

The runtime is loaded from:

```text
work\.opencode\specdiff-runtime
```

The repository under audit is read from the first `/spec-audit` argument. The audit workspace is kept under:

```text
work\.specdiff\audit
```

The final report is written to the requested output path.

## Main Artifacts

```text
commands/spec-audit.md
agents/spec-compliance-orchestrator.md
agents/code-investigator.md
tools/audit_start.ts
tools/audit_next.ts
tools/code_search.ts
tools/submit_batch_results.ts
tools/audit_finish.ts
skills/spec-code-consistency/SKILL.md
specdiff-runtime/specdiff
specdiff-runtime/specdiff-vendor-slim
```

The Python runtime owns requirements, Code Facts, evidence IDs, workflow state, validation, and final assembly.
OpenCode agents only investigate bounded batches and submit typed results.
