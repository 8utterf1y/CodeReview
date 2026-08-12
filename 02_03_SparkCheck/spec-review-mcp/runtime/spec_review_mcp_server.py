#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable


RUNTIME_ROOT = Path(__file__).resolve().parent
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from spec_review_runtime.cli import _dispatch, _resolve_repo  # noqa: E402
from spec_review_runtime.db import connect  # noqa: E402
from spec_review_runtime.locking import repository_lock  # noqa: E402


Json = dict[str, Any]


SERVER_NAME = "spec-review-mcp"
SERVER_VERSION = "0.1.0"


TOOL_SCHEMAS: list[Json] = [
    {
        "name": "spec_review_start",
        "description": "Start a requirements-code consistency review case. Use this first to lock scope, index code, parse requirement claims, and get the next review action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Absolute path of the business repository."},
                "docs": {"type": "array", "items": {"type": "string"}, "description": "Requirement or design document paths relative to repo, or absolute paths."},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Optional code paths to scope the review."},
                "sections": {"type": "array", "items": {"type": "string"}, "description": "Optional document sections to scope the review."},
                "mode": {"type": "string", "enum": ["fast", "deep", "auto"], "default": "auto"},
                "base": {"type": "string", "description": "Optional base commit/ref for diff review."},
                "head": {"type": "string", "description": "Optional head commit/ref. Defaults to HEAD."},
                "pr": {"type": "string", "description": "Optional PR/MR URL if the platform adapter supports it."},
                "fullRepo": {"type": "boolean", "description": "Set true to review the repository snapshot without diff/path scope."},
            },
            "required": ["repo", "docs"],
        },
    },
    {
        "name": "spec_review_status",
        "description": "Get review case status, current stage, coverage, and next action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "spec_review_context",
        "description": "Fetch bounded evidence packs for the current stage. The model reads this context before producing a stage result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
                "claimId": {"type": "string"},
                "gapId": {"type": "string"},
                "direction": {"type": "string", "enum": ["callers", "callees", "both"], "default": "both"},
                "maxNodes": {"type": "integer", "default": 40, "minimum": 1},
                "cursor": {"type": "integer", "default": 0, "minimum": 0},
                "limit": {"type": "integer", "default": 3, "minimum": 1},
                "query": {"type": "string"},
            },
            "required": ["repo", "caseId"],
        },
    },
    {
        "name": "spec_review_submit_stage",
        "description": "Submit the model's JSON result for the current review stage. The deterministic workflow validates the result before accepting it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
                "stage": {"type": "string", "enum": ["l3_review", "l4_initial", "l4_challenge", "l4_investigate", "l4_converge"]},
                "result": {"type": "object", "description": "Stage result JSON produced by the model."},
            },
            "required": ["repo", "caseId", "stage", "result"],
        },
    },
    {
        "name": "spec_review_next",
        "description": "Advance the deterministic workflow after a stage result has been submitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
            },
            "required": ["repo", "caseId"],
        },
    },
    {
        "name": "spec_review_finish",
        "description": "Finish the review case and generate the final traceable consistency report.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
            },
            "required": ["repo", "caseId"],
        },
    },
    {
        "name": "spec_review_publish_preview",
        "description": "Render a preview of the review content that would be published back to the code review platform. It does not write remotely.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
            },
            "required": ["repo", "caseId"],
        },
    },
    {
        "name": "spec_review_publish",
        "description": "Publish review output after checking that head commit did not drift. Keep dryRun true unless explicitly allowed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
                "expectedHeadSha": {"type": "string"},
                "dryRun": {"type": "boolean", "default": True},
                "event": {"type": "string", "default": "COMMENT"},
                "checkMode": {"type": "string", "enum": ["commit-status", "check-run"], "default": "commit-status"},
                "uploadSarif": {"type": "boolean", "default": False},
            },
            "required": ["repo", "caseId", "expectedHeadSha"],
        },
    },
    {
        "name": "spec_review_fix_preview",
        "description": "Generate a suggested patch preview for inconsistent findings. It does not change business code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
            },
            "required": ["repo", "caseId"],
        },
    },
    {
        "name": "spec_review_create_fix_pr",
        "description": "Create a fix PR only after explicit human confirmation. This is intentionally not part of the default review path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "caseId": {"type": "string"},
                "expectedHeadSha": {"type": "string"},
                "confirmation": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["repo", "caseId", "expectedHeadSha", "confirmation"],
        },
    },
]


TOOL_TO_OPERATION: dict[str, str] = {
    "spec_review_start": "start",
    "spec_review_status": "status",
    "spec_review_context": "context",
    "spec_review_submit_stage": "submit",
    "spec_review_next": "next",
    "spec_review_finish": "finish",
    "spec_review_publish_preview": "publish-preview",
    "spec_review_publish": "publish",
    "spec_review_fix_preview": "fix-preview",
    "spec_review_create_fix_pr": "create-fix-pr",
}


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        response = _handle_jsonrpc_line(line)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


def _handle_jsonrpc_line(line: str) -> Json | None:
    try:
        request = json.loads(line)
        if not isinstance(request, dict):
            return _error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return _result(request_id, _initialize_result())
        if method == "tools/list":
            return _result(request_id, {"tools": TOOL_SCHEMAS})
        if method == "tools/call":
            return _result(request_id, _call_tool(params))
        if request_id is None:
            return None
        return _error(request_id, -32601, f"Method not found: {method}")
    except json.JSONDecodeError as exc:
        return _error(None, -32700, f"Parse error: {exc.msg}")
    except Exception as exc:  # MCP clients expect tool errors to stay in protocol.
        return _error(
            request.get("id") if "request" in locals() and isinstance(request, dict) else None,
            -32000,
            f"{type(exc).__name__}: {exc}",
            {"traceback": traceback.format_exc(limit=5)},
        )


def _initialize_result() -> Json:
    return {
        "protocolVersion": "2024-11-05",
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "capabilities": {"tools": {}},
        "instructions": (
            "Use this server to run requirements-code consistency reviews. "
            "Start a case, fetch evidence context, produce stage JSON, submit it, "
            "advance the workflow, then finish or preview publication."
        ),
    }


def _call_tool(params: Json) -> Json:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name not in TOOL_TO_OPERATION:
        raise ValueError(f"Unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object")
    payload = dict(arguments)
    if name == "spec_review_submit_stage" and isinstance(payload.get("result"), dict):
        payload["result"] = json.dumps(payload["result"], ensure_ascii=False, separators=(",", ":"))
    result = _run_operation(TOOL_TO_OPERATION[name], payload)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, indent=2),
            }
        ]
    }


def _run_operation(operation: str, payload: Json) -> Json:
    repo = _resolve_repo(payload)
    with repository_lock(repo):
        with connect(repo) as connection:
            return _dispatch(connection, repo, operation, payload)


def _result(request_id: Any, result: Json) -> Json:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str, data: Json | None = None) -> Json:
    error: Json = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


if __name__ == "__main__":
    raise SystemExit(main())
