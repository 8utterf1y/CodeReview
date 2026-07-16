# Quick Test Mini F-Stack Fixture

This directory is a reduced local benchmark for fast SpecDiff regression testing.

## Contents

```text
quicktest-mini-fstack/
  repo/
    freebsd/netinet6/nd6.c
    freebsd/netinet6/nd6_nbr.c
    dpdk/lib/ip_frag/rte_ip_frag.h
    lib/ff_dpdk_if.c
  docs/benchmark.md
  answers/expected-issues.json
```

The fixture keeps only the source files needed for six IPv6/RFC consistency checks. It is intentionally small so a
full audit can finish much faster than scanning the complete F-Stack tree.

## Run With SpecDiff

Start OpenCode from the SpecDiff work directory, then run:

```text
/spec-audit /Users/8utterf1y/Desktop/agent项目/skills/quicktest-mini-fstack/repo /Users/8utterf1y/Desktop/agent项目/skills/quicktest-mini-fstack/docs/benchmark.md /Users/8utterf1y/Desktop/agent项目/skills/quicktest-mini-fstack/repo/.specdiff/issues.json
```

Expected reference answers are in:

```text
quicktest-mini-fstack/answers/expected-issues.json
```

Use this fixture for fast workflow checks, not as a replacement for the full benchmark.
