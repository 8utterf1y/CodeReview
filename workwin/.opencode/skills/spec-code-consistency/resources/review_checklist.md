# Review Checklist

Before finalizing each issue:

1. Is there a concrete spec quote or normalized requirement?
2. Is the requirement mandatory, recommended, optional, or contextual?
3. Which generic rule family applies, and what evidence does that family require?
4. Is there exact code evidence with file and line, or a documented absence search?
5. Did you inspect surrounding source context, not only one matching line?
6. Did you search for alternate implementation locations?
7. Did you distinguish docs/tests/examples/vendor code from production implementation?
8. Did you check configuration flags, platform branches, generated code, and adapters?
9. Did you look for tests proving the requirement is intentionally handled?
10. Did negative-evidence review keep, downgrade, candidate-only, or reject it?
11. Is the finding deduplicated by root cause?

If any answer is unknown, lower confidence or keep the item as a candidate.

Before finalizing the audit:

1. Does every extracted requirement appear in the coverage matrix?
2. Does every requirement have a status: `covered`, `violated`, `partial`, `no_evidence_found`, `unknown`, `out_of_scope`, or `non_verifiable`?
3. Does every requirement have `rule_family`, `evidence_strength`, `coverage_risk`, and searched tools?
4. Are `unknown`, `no_evidence_found`, `non_verifiable`, and high-risk requirements listed in `unverified_requirements`?
5. Did you record which tools were available and unavailable, including L1-L4 capability impact?
6. Did you avoid treating seed CLI issues as the full result?
7. Did you inspect requirements with no positive evidence rather than dropping them?
8. Did you avoid using weak evidence to mark a requirement as `covered`?
9. Did every final issue come only from `violated` or actionable `partial` coverage?

Rule-family gate review:

1. `module_presence`: entry point, registration/build enablement, and reachable behavior are all shown.
2. `parser_or_format`: parse/write logic, bounds, traversal, and invalid/unknown handling are checked.
3. `dispatch_or_routing`: classifier/route decision and handler call are shown.
4. `state_machine`: states, transition guards, invalid states, and terminal/recovery behavior are checked.
5. `timing_or_randomness`: timer/random/backoff/jitter is on the relevant behavior path.
6. `config_behavior`: option/default/load/validation/use site are connected.
7. `error_handling`: detection, failure propagation, cleanup/rollback, and caller behavior are checked.
8. `security_property`: boundary, enforcement point, and bypass search are documented.
9. `observability`: emission path exists for the required event.
10. `resource_lifecycle`: acquire/init, ownership, release, and failure-path cleanup are connected.
11. `compatibility_or_negotiation`: capability/version detection, fallback, and unsupported-case behavior are checked.
12. `data_consistency_or_mapping`: mapping, persistence/update path, conflict handling, and invariant/readback evidence are checked.
