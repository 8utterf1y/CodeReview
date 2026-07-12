---
name: spec-code-consistency
description: Audit canonical implementation requirements against a repository with indexed evidence, a focused Investigator, lightweight evidence review, and deterministic assembly.
---

# Spec-Code Consistency

Run `/spec-audit <requirements-path> <out-path>` from the repository being audited.

For a Markdown RFC inventory, first run `/prepare-rfcs <inventory-path> <candidate-requirements.json>`. It
downloads or reuses cached RFC Editor text, preserves original clauses and sections, and marks applicability as
unconfirmed. Review the generated scope before auditing a large corpus.

## Workflow

The Python program owns requirements, repository indexing, workflow transitions, query/evidence IDs, gates,
and final assembly. Agents never edit controlled artifacts.

1. `audit_start` locks requirements, builds/reuses Code Facts, and returns one `next_action`.
2. For `investigate`, the Orchestrator passes the supplied requirement unchanged to `code-investigator`.
3. Investigator uses `code_search` and submits one of `satisfied`, `mismatch`, or `uncertain`.
4. The program requests `evidence-reviewer` only for mismatch conclusions.
5. Reviewer checks the supplied packet once and submits `accept`, `reject`, or `uncertain`; it does not search.
6. `audit_next` supplies every transition. `audit_finish` alone writes JSON and SARIF.

## Evidence Rules

- Text, symbol, and Repo Map hits are navigation aids; exact source is stronger evidence.
- A missing keyword is not proof of missing behavior. Check an alternate name or path.
- Every cited evidence ID must come from `code_search` for the same requirement.
- Tool limitations produce `uncertain`, not invented path or data-flow conclusions.
- A reference inventory is scope, not an implementation obligation. Prefer canonical requirements JSON.

Read `resources/taxonomy.md` only when selecting a mismatch kind. Read
`resources/review_checklist.md` only when false-positive risk is unclear.
