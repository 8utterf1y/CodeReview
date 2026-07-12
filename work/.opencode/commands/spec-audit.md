---
description: Run the controlled SpecDiff workflow over design docs or an RFC inventory.
agent: spec-compliance-orchestrator
subtask: true
---

# Spec Audit

Usage: `/spec-audit <docs-path> <out-path>`

Literal arguments for this invocation:

```text
docs=$1
out=$2
```

Pass these exact expanded values to `audit_start` as `docs` and `out`. The current OpenCode directory is the
repository. Do not reinterpret paths or inspect files before `audit_start`.

Then follow only the `next_action` returned by `audit_start`/`audit_next` until `audit_finish` succeeds or the
workflow reports `blocked`.
