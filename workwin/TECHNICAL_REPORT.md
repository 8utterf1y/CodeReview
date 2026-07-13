# SpecDiff Technical Report

## 1. Goal

SpecDiff audits whether a repository implementation is consistent with design documents or RFC-based
specifications. The primary execution path is the OpenCode skill/tool workflow, not the legacy scanner CLI.

## 2. Main Workflow

```text
repo + docs + out
  -> audit_start
  -> explicit requirements or RFC corpus
  -> Requirement Pack Builder
  -> Code Facts SQLite index
  -> audit_next
  -> Code Investigator frames obligations
  -> frame_obligations
  -> audit_dispatch_result
  -> audit_next
  -> Code Investigator searches evidence
  -> submit_conclusion
  -> audit_dispatch_result
  -> Evidence Reviewer only for mismatch candidates
  -> audit_dispatch_result
  -> audit_finish
  -> issues.json + SARIF
```

The program controls state, evidence IDs, schema validation, mismatch gates, and final assembly. Agents only
investigate the bounded Requirement Pack they receive and submit typed results through tools.
Subagent completion is never inferred from natural language. `audit_dispatch_result` verifies the expected
state transition and either retries once or finalizes the failed action as unknown so the audit can continue.
Each dispatched worker task is recorded in `actions.json` with `action_id`, action type, requirement ID,
attempt, expected before/after state, status, and error. Supported lifecycle states are `created`,
`dispatched`, `committed`, `failed`, and `failed_terminal`.
`audit_dispatch_result` is a postcondition checker only: it marks action state but does not write investigations,
reviews, or requirement state. Terminal fallback is applied by the next `audit_next` call.

## 3. RFC Handling

An RFC inventory is treated as scope, not as direct implementation requirements. SpecDiff resolves referenced
RFC text, stores a corpus of clauses, computes effective scope such as `effective`, `overlay`,
`historical_context`, or `meta_spec`, and builds bounded Requirement Packs from normative behavior seeds plus
limited document context.

Every corpus clause receives a disposition such as `pack_seed`, `pack_context`, `definition_context`,
`historical_context`, `meta_spec`, `informational`, or `unclassified`. This prevents silent dropping of RFC
content while avoiding one audit task per RFC paragraph.

## 4. Code Facts

The OpenCode path builds `.specdiff/audit/code-index/codefacts.sqlite` with:

- files, languages, components, source roles, and build files
- symbols and references from bundled Aider Tree-sitter `tags.scm`
- candidate calls with `resolution` and `confidence`
- repo-map ranking from reference relationships
- tool coverage records

Current fallback is intentionally simple: if Tree-sitter/Aider tags are unavailable, semantic symbol/reference
coverage is reported as unavailable or partial, and `code_search` text mode remains available as navigation
only. There is no ctags, CodeQL, Joern, SCIP, or Semgrep backend in the current main path.

## 5. Mismatch Gate

Before a mismatch can reach the lightweight Reviewer, `frame_obligations` first stores program-controlled
obligations with stable IDs. `submit_conclusion` then enforces structured evidence, all obligation results, and
minimum negative checks. Missing-capability claims require checks for symbol/file search, alternative naming,
build/configuration, and responsibility. Behavior mismatch claims require an alternative-implementation check.
Every searched negative check must cite the `query_id` that produced it.

`frame_obligations`, `submit_conclusion`, and `submit_review` validate schema, references, and policy before
writing canonical artifacts. State transitions are centralized in the audit runtime; failed validation does not
modify requirement state.

The Reviewer does not search the repository. It only checks whether the supplied spec evidence, code evidence,
and reasoning support the mismatch. Only accepted mismatch or partial findings are assembled into final issues.

## 6. Validation

Synthetic tests cover:

- reference inventories are not direct requirements
- RFC2119 does not become a product implementation task
- obsolete RFCs do not duplicate effective RFC packs
- cross-section context is preserved in bounded packs
- missing capabilities still produce distributable packs
- every corpus clause has a disposition
- pack IDs and membership are deterministic
- code search returns coverage context
- heuristic calls are marked as heuristic/probable

Run tests from the repository root:

```bash
PYTHONPATH=work PYTHONPYCACHEPREFIX=/private/tmp/specdiff-pyc python3 -m unittest discover -s work/tests
```
