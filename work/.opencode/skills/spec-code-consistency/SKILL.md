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

1. `audit_start` locks requirements or Requirement Packs, builds/reuses Code Facts, and returns one `next_action`.
2. For `frame_obligations`, the Orchestrator passes the supplied `requirement_pack` unchanged to
   `code-investigator`.
3. Investigator calls `frame_obligations` with 1-3 implementation obligations derived only from supplied
   clause IDs. It must not search code in this phase.
4. For `investigate`, Investigator uses `code_search` against the program-stored obligations and submits
   `satisfied`, `mismatch`, or `uncertain` through `submit_conclusion`.
5. The program requests `evidence-reviewer` only for mismatch conclusions.
6. Reviewer checks the supplied packet once and submits `accept`, `reject`, or `uncertain`; it does not search.
7. `audit_next` supplies every transition. `audit_finish` alone writes JSON and SARIF.

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
