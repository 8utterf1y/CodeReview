# OpenCode Integration

This directory contains OpenCode-facing artifacts for turning SpecDiff into an interactive spec-to-code compliance workflow.

## Install into a target repository

From the submitted `work/` directory:

```bash
python3 install_opencode_interactive.py --target /path/to/repo --force
```

This copies:

- `.opencode/commands/spec-audit.md`
- `.opencode/agents/*.md`
- `.opencode/tools/*.ts`
- `.opencode/skills/spec-code-consistency/SKILL.md`
- `.opencode/specdiff-runtime/specdiff`
- `.opencode/specdiff-runtime/specdiff-vendor-slim`

Then start OpenCode from the target repository:

```bash
cd /path/to/repo
opencode
```

Run the interactive audit:

```text
/spec-audit /path/to/design-or-rfc-inventory.md .specdiff/issues.json
```

For a Markdown RFC inventory, `/spec-audit` internally resolves RFC text, builds a corpus, compresses it into
Requirement Packs, and audits those packs. `/prepare-rfcs` remains available for debugging the corpus builder,
but it is not a required user step.

The command writes:

- `.specdiff/issues.json`
- `.specdiff/issues.sarif`
- `.specdiff/audit/code-index/codefacts.sqlite`
- `.specdiff/audit/queries.jsonl`
- `.specdiff/audit/evidence.jsonl`

## Responsibility split

The Python runtime owns requirements, Code Facts, evidence IDs, state, gates, and final assembly. OpenCode
agents investigate and verify through typed tools:

1. load explicit requirements or compile an RFC inventory into Requirement Packs,
2. build SQLite Code Facts with Aider Tree-sitter tags,
3. frame 1-3 implementation obligations for each Requirement Pack,
4. investigate those obligations using controlled `code_search` queries,
5. review mismatch evidence once with a lightweight Reviewer,
6. assemble machine-readable findings programmatically.

Primary artifacts:

- `agents/spec-compliance-orchestrator.md`
- `agents/code-investigator.md`
- `agents/evidence-reviewer.md`
- `commands/spec-audit.md`
- `tools/audit_start.ts`
- `tools/audit_next.ts`
- `tools/code_search.ts`
- `tools/frame_obligations.ts`
- `tools/submit_conclusion.ts`
- `tools/submit_review.ts`
- `tools/audit_finish.ts`

`tools/submit_investigation.ts` is retained only as a legacy compatibility shim and is denied by the current
Investigator agent. The OpenCode path above is the controlled audit workflow; the legacy `python3 -m specdiff`
CLI is auxiliary scanner code.

Do not specialize the workflow for any public benchmark issue type. Public samples are validation fixtures only; the audit must be driven by extracted requirements, repository evidence, and the coverage matrix.
