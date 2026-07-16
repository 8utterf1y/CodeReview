# Spec-Code Mismatch Taxonomy

Use these categories when judging findings.

| Type | Meaning | Required Evidence |
| --- | --- | --- |
| `missing_in_code` | Required capability, module, endpoint, protocol message, transition, or config knob is absent. | Spec quote plus documented repository searches showing absence. |
| `partial_match` | Main path exists, but edge cases, variants, failure paths, cleanup, or compatibility behavior are missing. | Spec condition plus code path showing narrower behavior. |
| `mismatch` | Code behavior contradicts the specification. | Spec quote plus code line/path proving opposite behavior. |
| `code_weaker_than_spec` | Implementation has weaker limits, validation, timing, security, or guarantees. | Spec strength plus code evidence of weaker bound/condition. |
| `undocumented_extra_behavior` | Code has extra behavior affecting security, compatibility, persistence, observability, or user-visible semantics. | Code behavior plus absence/contradiction in design docs. |
| `spec_conflict` | Specs disagree and code implements one side without documenting the choice. | Two spec quotes plus code evidence of selected behavior. |

Severity defaults:

- `CRITICAL`: exploitable security issue, data loss, irreversible corruption, or normal-path protocol break.
- `HIGH`: MUST/REQUIRED violation, major interoperability break, mandatory feature missing.
- `MEDIUM`: SHOULD-level violation, important optional behavior, substantial edge-case failure.
- `LOW`: narrow edge case, documentation drift, minor compatibility issue.
