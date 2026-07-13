# SpecDiff Controlled Audit Design

## Goals

SpecDiff checks arbitrary parsed requirements against a repository. A public benchmark is a test fixture,
not a rule catalogue. The design therefore separates deterministic control and evidence collection from
LLM judgment.

## Architecture

```text
parsed requirements JSON
        | lock and hash
        v
program-controlled audit state <----- repository
        |                                  |
        |                         Mini Code Facts Builder
        |                                  |
        |                         SQLite Code Facts DB
        |                                  |
        +---------- controlled query API --+
                           |
                  Code Investigator
                           |
                  typed investigation form
                           |
               risk-based verification gate
                           |
             Evidence Verifier when required
                           |
                   typed verification form
                           |
                  deterministic assembler
                           |
                 issues.json + SARIF 2.1.0
```

## Control Plane

The Python runtime owns requirement locking, state transitions, query/evidence IDs, submission validation,
verification policy, and final assembly. OpenCode agents cannot directly read the repository, edit controlled
artifacts, or write the result. They interact only through typed tools.

This prevents an agent from skipping an indexed search, inventing a line number, changing a requirement, or
declaring completion before every requirement reaches a terminal state.

## Code Facts V1

The reusable `.specdiff/audit/code-index/codefacts.sqlite` stores:

- files, source roles, components, hashes, and language metadata;
- build files and lightweight build inclusion facts;
- Tree-sitter definitions and references extracted with Aider `tags.scm` queries;
- candidate call relationships, explicitly marked as syntax-level rather than compiler-precise;
- repository ranking inspired by Aider Repo Map;
- per-tool execution and coverage metadata.

Text search and exact source reads remain available through the same controlled API. Path and data-flow
queries return an explicit capability limitation until SCIP, CodeQL, or Joern backends are installed.

## Agent Roles

`code-investigator` investigates one immutable requirement. It navigates from repository map and concepts to
symbols, references, callers, build facts, and exact source. It must submit existing query and evidence IDs.

`evidence-reviewer` is not a forced opponent and does not repeat repository search. For mismatch conclusions,
it receives a compact requirement, claim, evidence, and limitation packet, then returns one semantic judgment.

## Form And Assembly Gates

OpenCode tools use field-level Zod schemas. The Python backend validates the same enums, confidence range,
required issue fields, ownership of query IDs, and ownership of evidence IDs. Zod improves Agent compliance;
backend validation protects against alternate callers.

The assembler is the only writer of final findings. It emits an issue only for an accepted `violated` or
actionable `partial` investigation, preserves exact evidence, records unresolved requirements, and writes
SARIF beside JSON.

## Planned Semantic Backends

V1 deliberately does not pretend that syntax references are a precise call graph. Later adapters can add:

1. compile database and SCIP/LSP definition-reference facts;
2. CodeQL for compiled path, control-flow, and data-flow obligations;
3. Joern for C/C++ CPG exploration where compilation is incomplete.

Each adapter must write provenance and coverage into Code Facts. Agents may use only capabilities reported as
successfully executed for the current repository.
