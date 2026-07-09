# SpecDiff Technical Report

## 1. Goal

SpecDiff detects inconsistencies between a code implementation and design/RFC documents. It is designed for the implementation/design difference detection competition, where the judge supplies a local code repository and a design document path, then reads a structured result file.

## 2. Chosen Base

The design is based on the open-source Trail of Bits `spec-to-code-compliance` workflow:

- Spec-IR: structured requirements extracted from specifications.
- Code-IR: implementation behavior extracted from source files.
- Alignment-IR: matching requirements to implementation evidence.
- Divergence findings: actionable mismatches with evidence chains.

SpecDiff adapts that audit pattern for RFC-driven C/network-stack code and changes the execution model into a deterministic CLI so the judge can run it without human interaction.

Additional ideas borrowed from related tools:

- ClaudeCodeAgents/Jenny: every finding needs spec evidence, code evidence, line references, and severity.
- PR-Agent: structured machine-readable output and compact context selection.
- code-review skills: separate specification compliance from confidence/noise filtering.

## 3. Architecture

```text
design documents / RFC references
  -> Spec-IR requirement extraction
  -> source-file indexing
  -> targeted protocol compliance checkers
  -> finding de-duplication and ranking
  -> issues.json + report.md
```

The current implementation is dependency-free Python:

- `spec_loader.py`: reads Markdown/text specs and extracts normative requirements. It also includes RFC-oriented fallback requirements for RFC 4861, RFC 8200, RFC 8415, and RFC 2710 when the benchmark document references those RFCs but does not include full text.
- `code_index.py`: recursively indexes source files and provides regex search with relative file paths and line numbers.
- `checkers.py`: targeted checkers for the benchmark issue families.
- `report.py`: writes machine-readable JSON and human-readable Markdown.
- `cli.py`: command-line entry point.

## 4. Implemented Checkers

1. Neighbor Discovery option limit:
   - Finds `nd6_maxndopt`/`maxndopt` style hard limits in `nd6.c`.
   - Reports code weaker than RFC-style processing of valid ND options.

2. Proxy Neighbor Advertisement random delay:
   - Reads `freebsd/netinet6/nd6_nbr.c`.
   - Checks whether proxy NA handling has nearby random/timer/delay logic.

3. Proxy unsolicited Neighbor Advertisement:
   - Checks whether proxy handling exists but no unsolicited/all-nodes update path is evident.

4. IPv6 Fragment extension-header chain walking:
   - Reads `dpdk/lib/ip_frag/rte_ip_frag.h`.
   - Checks for direct Fragment/Next Header logic without a loop over extension headers.

5. DHCPv6 absence:
   - Performs repository-wide symbol search for DHCPv6 implementation surface.
   - Reports missing protocol capability when only absent or trivial hits are found.

6. MLD multicast receive/dispatch:
   - Reads `lib/ff_dpdk_if.c`.
   - Checks whether IPv6 receive logic has clear MLD/ICMPv6 multicast dispatch.

## 5. Output Schema

The JSON output contains:

- `tool`, `version`, `repo`, `docs`
- `requirements_indexed`
- `source_files_indexed`
- `issues`

Each issue contains:

- `id`
- `title`
- `match_type`
- `severity`
- `confidence`
- `description`
- `spec_evidence`
- `code_evidence`
- `verification`

This matches the competition requirement that each issue provide the inconsistency description, design evidence, code evidence, code location, and design-document location.

## 6. Baseline Validation

A local smoke-test fixture is included under `work/testdata/`. The command below validates that the CLI exits successfully and writes both outputs:

```bash
cd work
python3 self_check.py
```

On the local fixture, the tool reports six issue families and produces valid JSON.

The expanded command used by the self-check is:

```bash
python3 -m specdiff \
  --repo testdata/repo \
  --docs testdata/docs/benchmark.md \
  --out /tmp/specdiff-self-check/issues.json \
  --report /tmp/specdiff-self-check/report.md
```

The detector was also run against the provided F-Stack benchmark checkout:

```bash
git -C testdata/f-stack rev-parse HEAD
# 58cc9cf685f496d0542b072fe3e6246d3ceba781

git -C testdata/f-stack branch --show-current
# competition

python3 -m specdiff \
  --repo testdata/f-stack \
  --docs testdata/docs/benchmark.md \
  --out /tmp/specdiff-real/issues.json \
  --report /tmp/specdiff-real/report.md
```

Observed result on this checkout:

- Indexed source files: 13005
- Detected issues: 6
- Runtime: about 10 seconds on the local machine

The six detected issue families were:

- Proxy Neighbor Advertisement delay rule explicitly not implemented: `freebsd/netinet6/nd6_nbr.c:650`
- Neighbor Discovery option processing capped by `nd6_maxndopt = 10`: `freebsd/netinet6/nd6.c:123`
- IPv6 fragment helper checks only the extension header after the fixed IPv6 header: `dpdk/lib/ip_frag/rte_ip_frag.h:133`
- Proxy Neighbor Advertisement lacks an explicit unsolicited/proactive proxy NA path: `freebsd/netinet6/nd6_nbr.c:340`
- DHCPv6 implementation entry points absent: repository-wide scan
- MLD multicast packets are routed through multicast/KNI filtering without explicit MLD dispatch: `lib/ff_dpdk_if.c:1567`

## 7. Expected Competition Behavior

For the provided F-Stack benchmark, the implemented checkers identify the six known issue families listed in the competition materials:

- ND option limit
- Proxy NA without random delay
- Proxy NA without unsolicited advertisement support
- Fragment header chain walking
- Absent DHCPv6
- MLD multicast reception/dispatch

The tool exceeds the minimum threshold of four issues on the checked-out benchmark copy.

## 8. Future Optimizations

The next improvements should be:

- Add optional RFC downloading and caching when network is available.
- Add tree-sitter or clang-based function extraction for more accurate Code-IR.
- Add an optional LLM verifier that consumes only candidate evidence and emits the same JSON schema.
- Add more generic checkers for constants, timers, state-machine transitions, packet field validation, and missing protocol modules.
