---
name: spec-code-consistency
description: Audit a codebase against design documents, RFCs, or other specifications and report implementation inconsistencies with evidence chains.
---

# Spec-Code Consistency Audit

Use this skill when asked to determine whether code implements a design document, RFC, whitepaper, protocol description, or product specification.

## Core Principle

Every finding must be grounded in both sides of the evidence chain:

1. A concrete requirement from the specification.
2. A concrete implementation behavior from the code.

Do not report a mismatch based only on protocol intuition, general knowledge, or absent context. If code is missing, show what was searched and why the absence is meaningful.

## Workflow

1. Build a Spec-IR:
   - Extract normative requirements, especially `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, required state transitions, packet formats, algorithms, limits, timers, and error handling.
   - Record document name, section, short quote, normalized requirement, and key terms.

2. Build a Code-IR:
   - Index relevant files, functions, macros, constants, call sites, conditionals, timers, randomization calls, parser loops, and protocol dispatch paths.
   - Record file path, line number, code quote, and inferred behavior.

3. Align Spec-IR to Code-IR:
   - For each requirement, find likely implementation locations by protocol terms, symbol names, constants, packet names, and repository layout.
   - Classify the match as `full_match`, `partial_match`, `mismatch`, `missing_in_code`, `code_weaker_than_spec`, or `uncertain`.

4. Report only actionable divergences:
   - Missing required behavior.
   - Incorrect or incomplete behavior.
   - Code weaker than a mandatory or strongly recommended specification.
   - Code behavior that contradicts a prohibition.

5. De-duplicate and rank:
   - Prefer high-confidence findings with precise code lines.
   - Merge multiple symptoms of the same root cause.
   - Lower confidence when a finding relies mainly on absence.

## Finding Format

Each finding should include:

- title
- match type
- severity
- confidence
- specification evidence: document, section, quote
- code evidence: file, line, quote
- reasoning
- verification steps

## Competition-Specific Notes

For the implementation/design difference detection benchmark, prioritize RFC compliance issues in F-Stack:

- IPv6 Neighbor Discovery option handling.
- Proxy Neighbor Advertisement timing and unsolicited behavior.
- IPv6 extension header and fragmentation parsing.
- DHCPv6 implementation presence.
- Multicast Listener Discovery receive/dispatch behavior.

The automatic judge should run the CLI in `work/specdiff`; this skill is the audit method, not the only execution mechanism.
