---
description: Compile an RFC inventory into source-linked candidate requirements JSON.
subtask: false
---

# Prepare RFC Requirements

Usage: `/prepare-rfcs <inventory-path> <out-path>`

Call `prepare_rfcs` once with:

```text
inventory=$1
out=$2
```

Report the output path, emitted requirement count, excluded vocabulary references, and limitations. Do not audit
the repository in this command.
