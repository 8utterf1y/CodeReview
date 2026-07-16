---
description: Run the controlled SpecDiff workflow over design docs or an RFC inventory.
agent: spec-compliance-orchestrator
subtask: true
---

# Spec Audit

Usage: `/spec-audit <repo-path> <docs-path> <out-path>`

Literal arguments for this invocation:

```text
repo=$1
docs=$2
out=$3
```

Pass these exact expanded values to `audit_start` as `repo`, `docs`, and `out`. The current OpenCode directory is
the SpecDiff project root; the repository under audit is the `repo` argument. Do not reinterpret paths or inspect
files before `audit_start`.

Then follow only the `next_action` returned by `audit_start`/`audit_next` until `audit_finish` succeeds or the
workflow reports `blocked`.
