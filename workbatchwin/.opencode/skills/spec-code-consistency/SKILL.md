---
name: spec-code-consistency
description: Audit design documents or RFC inventories against a repository with Requirement Packs, indexed evidence, a focused Investigator, lightweight evidence review, and deterministic assembly.
---

# Spec-Code Consistency

Run `/spec-audit <docs-path> <out-path>` from the repository being audited.

`docs-path` may be a canonical requirements JSON, an explicit-obligation design document, or an RFC inventory.
For an RFC inventory, `/spec-audit` internally downloads or reuses cached RFC Editor text, creates an RFC corpus,
builds bounded Requirement Packs, and audits those packs. `/prepare-rfcs` is a debugging helper, not a required
manual step.

## Workflow

The Python program owns requirements, repository indexing, workflow transitions, query/evidence IDs, gates,
and final assembly. Agents never edit controlled artifacts.

1. `audit_start` locks requirements or Requirement Packs, builds/reuses Code Facts, builds Audit Batches, and
   returns one `next_action`.
2. For `investigate_batch`, the Orchestrator passes the supplied batch unchanged to `code-investigator`.
3. Investigator uses `code_search` and submits per-Pack results through `submit_batch_results`.
4. If a batch returns incomplete, the next `audit_next` fills missing Pack results as `unknown`.
5. `audit_finish` alone writes JSON and SARIF.

Each `audit_next` worker packet contains an `action_id`. Pass that same `action_id` to `audit_dispatch_result`.
Do not reuse an old action ID after the runtime returns a retry packet.
If `audit_next` returns `awaiting_dispatch_result`, call `audit_dispatch_result` for that action before doing
anything else.

## Evidence Rules

- Text, symbol, and Repo Map hits are navigation aids; exact source is stronger evidence.
- A missing keyword is not proof of missing behavior. Check an alternate name or path.
- Every cited evidence ID must come from `code_search` for the same requirement.
- A searched negative check must cite the `query_id` that performed the search.
- Tool limitations produce `uncertain`, not invented path or data-flow conclusions.
- Tree-sitter/Aider tags provide the current symbol/reference index. If unavailable, semantic index coverage is
  reported as unavailable and text search remains only a navigation aid.
- A reference inventory is scope, not an implementation obligation; RFC rows are compiled into corpus and
  Requirement Packs before investigation.

Read `resources/taxonomy.md` only when selecting a mismatch kind. Read
`resources/review_checklist.md` only when false-positive risk is unclear.
