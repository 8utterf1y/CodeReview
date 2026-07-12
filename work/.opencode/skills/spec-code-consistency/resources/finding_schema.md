# Finding JSON Schema

Final output must be machine-readable JSON:

```json
{
  "tool": "opencode-specdiff",
  "repo": "/absolute/repo",
  "docs": "/absolute/docs",
  "agent_review": {
    "status": "completed | partial | not_run",
    "agents_invoked": [
      "spec-requirement-miner",
      "code-behavior-mapper",
      "alignment-judge",
      "negative-evidence"
    ],
    "artifact": ".specdiff/issues.json.agent-review.json",
    "notes": ["short review status or failure reason"]
  },
  "coverage_summary": {
    "requirements_total": 12,
    "status_counts": {
      "covered": 3,
      "violated": 2,
      "partial": 1,
      "no_evidence_found": 4,
      "unknown": 2
    },
    "rule_family_counts": {
      "parser_or_format": 3,
      "resource_lifecycle": 2
    },
    "high_risk_requirements": ["REQ-007"]
  },
  "rule_family_stats": {
    "parser_or_format": {
      "description": "Field, schema, message, file, packet, or protocol format behavior.",
      "covered_requires": "Strong parser evidence, or complementary medium evidence proving read/write, bounds, and variant handling."
    }
  },
  "tool_status": [
    {
      "name": "text-index",
      "level": "L1",
      "status": "available",
      "purpose": "text and symbol search",
      "detail": "built-in regex search",
      "impact": "baseline evidence only"
    },
    {
      "name": "codeql",
      "level": "L3",
      "status": "unavailable",
      "purpose": "semantic/static analysis",
      "detail": "install or configure for code-flow coverage",
      "impact": "lower confidence for data-flow and security claims"
    }
  ],
  "requirements": [
    {
      "id": "REQ-001",
      "status": "covered | violated | partial | no_evidence_found | unknown | out_of_scope | non_verifiable",
      "rule_family": "parser_or_format",
      "evidence_strength": "strong | medium | weak | none",
      "coverage_risk": "low | medium | high",
      "confidence": 0.72,
      "spec_evidence": {
        "document": "design.md",
        "section": "3.2",
        "quote": "Short quote or normalized requirement."
      },
      "positive_evidence": [
        {"file": "src/example.c", "line": 123, "quote": "Relevant implementation evidence."}
      ],
      "negative_evidence": [
        "Searches or counter-evidence checked."
      ],
      "searched_with": ["text-index", "symbol-lite", "ast-grep", "semgrep", "codeql", "joern"],
      "notes": ["Why this status is justified."]
    }
  ],
  "unverified_requirements": [
    {"id": "REQ-007", "reason": "No semantic tool available for data-flow verification."}
  ],
  "issues": [
    {
      "id": "ISSUE-001",
      "requirement_id": "REQ-001",
      "title": "Short actionable title",
      "match_type": "missing_in_code",
      "severity": "HIGH",
      "confidence": 0.86,
      "description": "What is inconsistent and why it matters.",
      "spec_evidence": {
        "document": "design.md",
        "section": "3.2",
        "quote": "Short quote or normalized requirement."
      },
      "code_evidence": {
        "file": "src/example.c",
        "line": 123,
        "quote": "Relevant code line or absence-search summary.",
        "note": "Why this code proves the behavior."
      },
      "verification": [
        "Search/read steps performed.",
        "Counter-evidence checked.",
        "Reason final classification is not a false positive."
      ],
      "false_positive_risk": "low"
    }
  ]
}
```

Rules:

- Do not emit candidates as final issues.
- Emit final issues only for `violated` requirements and actionable `partial` requirements.
- Put `unknown`, `no_evidence_found`, `non_verifiable`, and high-risk requirements in `unverified_requirements`.
- Do not omit requirements from the final coverage matrix.
- Do not mark the audit complete when high-risk unverified requirements remain without an explicit note.
- Do not mark a requirement `covered` from weak evidence.
- `covered` requires strong evidence or multiple complementary medium evidence items that jointly pass the global and family coverage gates.
- Keep quotes short.
- Use absolute or repository-relative file paths consistently.
- `confidence` must be between `0.0` and `1.0`.
- Include `false_positive_risk`: `low`, `medium`, or `high`.
