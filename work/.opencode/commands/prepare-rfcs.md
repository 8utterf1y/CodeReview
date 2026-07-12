---
description: Compile an RFC inventory into an RFC corpus and bounded Requirement Packs for debugging.
subtask: false
---

# Prepare RFC Corpus

Usage: `/prepare-rfcs <inventory-path> <out-path>`

Call `prepare_rfcs` once with:

```text
inventory=$1
out=$2
```

Report the output path, corpus clause count, Requirement Pack count, excluded vocabulary references, and
limitations. Do not audit the repository in this command.
