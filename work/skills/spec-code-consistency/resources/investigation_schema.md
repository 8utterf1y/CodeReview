# Investigation Artifacts

Use three separate JSON artifacts. Agents may add explanatory fields, but must preserve these fields.

## Requirement Models

```json
{
  "schema_version": "1.0",
  "artifact_type": "requirement_models",
  "requirements": [{
    "id": "REQ-001",
    "source": {"document": "spec.md", "section": "4", "quote": "...", "normalized": "..."},
    "interpretation": {
      "statement": "...",
      "normative_level": "MUST|SHOULD|MAY|informative|unresolved",
      "conditions": [], "exceptions": [], "scope_notes": []
    },
    "responsibility": {
      "status": "confirmed|unresolved|out_of_scope|non_verifiable",
      "expected_components": [], "reasoning": "...",
      "must_resolve_before_missing_finding": true
    },
    "behavior_model": {
      "triggers": [], "preconditions": [], "required_actions": [],
      "forbidden_behaviors": [], "observable_effects": [], "failure_behaviors": []
    },
    "proof_obligations": [{
      "id": "REQ-001-PO-1", "claim": "...", "kind": "...",
      "evidence_needed": ["..."], "success_condition": "...",
      "contradiction_condition": "..."
    }],
    "uncertainties": [], "inferred": false
  }]
}
```

## Investigation

```json
{
  "schema_version": "1.0",
  "artifact_type": "investigation",
  "investigations": [{
    "requirement_id": "REQ-001",
    "obligation_results": [{
      "obligation_id": "REQ-001-PO-1",
      "status": "supported|contradicted|unresolved|not_applicable",
      "queries": [{
        "type": "concept_search|symbol_definition|references|callers|callees|ast|control_flow|data_flow|build_inclusion|absence_search|bypass_search",
        "purpose": "...", "parameters": {}, "tools": [], "result_summary": "..."
      }],
      "evidence": [{"file": "src/a.c", "line": 10, "quote": "...", "role": "..."}],
      "reasoning": "...", "unresolved_questions": []
    }],
    "counterexample_searches": [],
    "proposed_status": "covered|violated|partial|no_evidence_found|unknown|out_of_scope|non_verifiable",
    "proposed_findings": []
  }]
}
```

## Verification

```json
{
  "schema_version": "1.0",
  "artifact_type": "verification",
  "verifications": [{
    "requirement_id": "REQ-001",
    "verdict": "accepted|rejected|needs_more_work",
    "challenges": [{"type": "missed_path", "description": "...", "evidence": []}],
    "reasoning": "...",
    "recommended_status": "unknown"
  }]
}
```
