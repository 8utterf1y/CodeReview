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
3. investigate each Requirement Pack using controlled queries,
4. review mismatch evidence once with a lightweight Reviewer,
5. assemble machine-readable findings programmatically.

Primary artifacts:

- `agents/spec-compliance-orchestrator.md`
- `agents/code-investigator.md`
- `agents/evidence-reviewer.md`
- `commands/spec-audit.md`
- `tools/audit_start.ts`
- `tools/audit_next.ts`
- `tools/code_search.ts`
- `tools/submit_investigation.ts`
- `tools/submit_review.ts`
- `tools/audit_finish.ts`

The legacy `python3 -m specdiff` CLI is auxiliary scanner code. The OpenCode path above is the controlled audit
workflow.

Do not specialize the workflow for any public benchmark issue type. Public samples are validation fixtures only; the audit must be driven by extracted requirements, repository evidence, and the coverage matrix.
