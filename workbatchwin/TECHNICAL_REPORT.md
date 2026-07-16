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
  -> Batch Planner
  -> Code Investigator investigates one batch
  -> submit_batch_results
  -> audit_next fills missing Pack results as unknown
  -> audit_finish
  -> issues.json + SARIF
```

The program controls state, evidence IDs, schema validation, mismatch gates, and final assembly. Agents only
investigate the bounded batch they receive and submit typed per-Pack results through tools. Pack remains the
result and coverage unit; Batch is only the Agent dispatch unit.

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

`submit_batch_results` validates that every result belongs to the active batch, each Pack appears at most once,
clause IDs belong to that Pack, evidence IDs belong to that Pack, and violated results include an issue.
If the Agent omits a Pack, the next `audit_next` writes an `unknown` result for that Pack and continues.

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

Run tests from the Windows `work` directory:

```powershell
cd C:\judge-assets\01_03_ai_implementation_design_difference_detection\work
$env:PYTHONPATH = "."
python -m unittest discover -s tests
```
