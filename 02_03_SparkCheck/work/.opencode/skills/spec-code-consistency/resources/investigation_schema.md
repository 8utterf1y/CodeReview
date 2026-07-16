# Investigation Artifacts

Use program-owned artifacts. Agents do not write these files directly; they fill typed tool forms.

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

## Obligation Framing

```json
{
  "schema_version": "1.0",
  "artifact_type": "obligation_framing",
  "requirement_id": "REQ-001",
  "obligations": [{
    "description": "Implementation behavior to check",
    "source_clause_ids": ["RFC4861-7.2.8-001"]
  }]
}
```

The runtime assigns stable obligation IDs. Provide 1-3 obligations only, and use clause IDs from the supplied
Requirement Pack.

## Investigation Conclusion

```json
{
  "schema_version": "1.0",
  "artifact_type": "investigation_conclusion",
  "investigations": [{
    "requirement_id": "REQ-001",
    "conclusion": "satisfied|mismatch|uncertain",
    "obligation_results": [{
      "obligation_id": "OBL-...",
      "status": "supported|contradicted|partial|not_found|unresolved",
      "evidence_ids": ["E-..."]
    }],
    "negative_checks": [{
      "dimension": "symbol_or_file_search|alternative_naming|build_or_configuration|responsibility|alternative_implementation",
      "status": "searched|not_applicable|inconclusive",
      "query_ids": ["Q-..."],
      "result": "..."
    }],
    "summary": "...",
    "proposed_findings": [],
    "uncertainties": []
  }]
}
```

A searched negative check must cite the query IDs that support it. Evidence IDs and query IDs must come from
`code_search` for the active batch or the same requirement.

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
