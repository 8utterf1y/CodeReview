# Spec Review MCP

This directory is a copy of `spec-review-opencode` with an added MCP stdio server.
The original OpenCode package is not modified.

## What MCP Adds

MCP turns the deterministic review runtime into tools that a host Agent can call.
The model does not execute Git, parse AST, or write reports directly. It calls MCP
tools, reads the returned evidence context, produces stage JSON, and submits that
JSON back to the runtime for validation and state transition.

## Tool Flow

1. `spec_review_start`
   - Inputs: `repo`, `docs`, optional `base/head`, `paths`, `sections`, `mode`, `pr`.
   - Runtime work: resolves scope, builds or updates the Tree-sitter index, parses
     requirement claims, records base/head metadata, and returns the first action.
   - Model work: checks the returned `next_action` and decides which evidence page
     to request.

2. `spec_review_context`
   - Inputs: `repo`, `caseId`, optional `claimId`, `gapId`, `direction`, `cursor`,
     `limit`, `query`.
   - Runtime work: returns bounded evidence packs containing requirement claims,
     diff snippets, source symbols, and caller/callee graph context.
   - Model work: reads the evidence, identifies candidate inconsistencies, searches
     for counter-evidence, and prepares the current stage result.

3. `spec_review_submit_stage`
   - Inputs: `repo`, `caseId`, `stage`, `result`.
   - Runtime work: validates the stage JSON against workflow rules and persists it.
   - Model work: supplies structured conclusions with evidence IDs instead of free
     text only.

4. `spec_review_next`
   - Inputs: `repo`, `caseId`.
   - Runtime work: advances the deterministic state machine.
   - Model work: follows the returned next action. In auto mode, this may move from
     fast review to deep review when uncertainty or inconsistency exists.

5. `spec_review_finish`
   - Inputs: `repo`, `caseId`.
   - Runtime work: generates the final traceable report.
   - Model work: summarizes the result for the user.

6. `spec_review_publish_preview`
   - Inputs: `repo`, `caseId`.
   - Runtime work: renders the review content that would be posted back to the code
     review platform. It does not write remotely.
   - Model work: shows the preview and asks for explicit approval before publishing.

7. `spec_review_publish`
   - Inputs: `repo`, `caseId`, `expectedHeadSha`, optional `dryRun`, `event`,
     `checkMode`, `uploadSarif`.
   - Runtime work: checks head SHA drift and publishes only when allowed. Keep
     `dryRun=true` unless the user explicitly authorizes remote writeback.
   - Model work: gates the action on human approval and reports the outcome.

8. `spec_review_fix_preview`
   - Inputs: `repo`, `caseId`.
   - Runtime work: generates a suggested patch preview.
   - Model work: explains the suggested change. It does not modify business code.

9. `spec_review_create_fix_pr`
   - Inputs: `repo`, `caseId`, `expectedHeadSha`, `confirmation`, optional `title`,
     `body`.
   - Runtime work: creates a fix PR only after explicit confirmation.
   - Model work: treats this as a separate, human-approved repair workflow.

## Example MCP Configuration

Copy `mcp.example.json` and replace the placeholder path with this directory's
absolute path:

```json
{
  "mcpServers": {
    "spec-review": {
      "command": "python3",
      "args": [
        "/Users/8utterf1y/Desktop/agent项目/skills/02_03_SparkCheck/spec-review-mcp/runtime/spec_review_mcp_server.py"
      ]
    }
  }
}
```

## Example Natural Language Use

After the MCP server is configured in a client that supports MCP, the user can ask:

```text
审查这个仓库中 requirements/EXPENSE_PAYMENT_REQUIREMENTS.md 与当前实现是否一致，使用 auto 模式。
```

The host Agent should call:

```text
spec_review_start -> spec_review_context -> spec_review_submit_stage
-> spec_review_next -> ... -> spec_review_finish
```

The user does not need to remember these commands. The host Agent chooses tools
based on the conversation and the workflow state returned by the runtime.

## Local Protocol Smoke Test

Run from this directory:

```bash
python3 runtime/spec_review_mcp_server.py
```

Then send JSON-RPC lines on stdin, for example:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

The server should return `serverInfo` and the tool list.
