from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .repository_index import build_repository_index, load_files, load_repository
from .codefacts import query_codefacts


INVESTIGATION_STATUSES = {"covered", "violated", "partial", "no_evidence_found", "unknown", "out_of_scope", "non_verifiable"}
VERIFICATION_VERDICTS = {"accepted", "rejected", "needs_more_work"}
QUERY_MODE_ALIASES = {
    "reference": "references", "refs": "references",
    "definition": "symbol", "definitions": "symbol", "defs": "symbol",
    "call": "callers",
}
MAX_SUBAGENT_ATTEMPTS = 2
TARGET_BATCHES = 24
HARD_MAX_BATCHES = 30
MIN_TOPIC_MERGE_SCORE = 6.0
MAX_BATCH_PACKET_PACKS = 12
MAX_BATCH_PACKET_CLAUSES = 160
MAX_BATCH_QUERIES = 120
MAX_BATCH_TEXT_QUERIES = 60
MAX_DISCOVERY_SOURCE_WINDOWS = 8
MAX_DISCOVERY_SYMBOLS = 12
MAX_DISCOVERY_FILES = 8
LOW_VALUE_SYMBOL_FAMILIES = {
    "get", "set", "test", "member", "default", "include", "lib", "app", "src", "cmd",
    "cache", "freebsd", "contrib", "ngx", "redis", "rte", "uni", "server", "client",
    "main", "init", "create", "delete", "update", "find", "read", "write",
    "generate", "translate", "accept", "hook", "linux", "ngbe", "dpdk", "drivers",
    "actions", "port", "device", "bindings", "common", "sys", "http", "nginx",
    "openzfs", "agents", "free",
    "setdestaddress", "libfdt", "fdt", "cpswp", "pcd",
}
LOW_VALUE_COMPONENT_PATTERNS = (
    r"^app/",
    r"^freebsd/contrib(?:/|$)",
    r"^dpdk/drivers(?:/|$)",
    r"(^|/)(?:test|tests|example|examples|doc|docs)(?:/|$)",
)
HIGH_VALUE_COMPONENT_PREFIXES = (
    "freebsd/netinet6",
    "freebsd/netinet",
    "freebsd/net",
    "dpdk/lib",
    "lib",
    "adapter",
)


def init_audit(repo: Path, requirements_path: Path, workspace: Path, out: Optional[Path] = None) -> Dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    raw_requirements = _load_json(requirements_path)
    requirements = _normalize_requirements(raw_requirements)
    if not requirements:
        raise ValueError("requirements JSON contains no requirements")
    _persist_spec_artifacts(workspace, raw_requirements)
    index_dir = workspace / "code-index"
    repository = build_repository_index(repo, index_dir)
    locked = {"schema_version": "1.0", "requirements": requirements}
    _write_json(workspace / "requirements.json", locked)
    state = {
        "schema_version": "1.0", "audit_id": _audit_id(repo, requirements),
        "repo": str(repo.resolve()), "requirements_source": str(requirements_path.resolve()),
        "requested_output": str(out.resolve()) if out else None,
        "requirements_sha256": _sha256_json(locked), "code_revision": repository["revision"],
        "stage": "investigating", "assembly_allowed": False,
        "requirements": {item["id"]: {"investigation": "pending", "verification": "pending"} for item in requirements},
        "batch_cursor": 0, "active_batch_id": None, "batch_mode": True,
        "counters": {"query": 0, "evidence": 0, "action": 0}, "created_at": _now(), "updated_at": _now(),
    }
    _write_json(workspace / "audit-state.json", state)
    _write_json(workspace / "batches.json", {"schema_version": "1.0", "batches": _build_audit_batches(workspace, requirements)})
    _write_json(workspace / "actions.json", {"schema_version": "1.0", "actions": []})
    _write_json(workspace / "investigation-drafts.json", {"schema_version": "1.0", "drafts": []})
    _write_json(workspace / "investigations.json", {"schema_version": "1.0", "investigations": []})
    _write_json(workspace / "verifications.json", {"schema_version": "1.0", "verifications": []})
    (workspace / "queries.jsonl").touch()
    (workspace / "evidence.jsonl").touch()
    return audit_status(workspace)


def audit_status(workspace: Path) -> Dict[str, Any]:
    state = _state(workspace)
    counts = Counter()
    for item in state["requirements"].values():
        counts[f"investigation_{item['investigation']}"] += 1
        counts[f"verification_{item['verification']}"] += 1
    return {
        "audit_id": state["audit_id"],
        "stage": state["stage"],
        "assembly_allowed": state["assembly_allowed"],
        "counts": dict(counts),
        "pending_investigations": [
            req_id for req_id, item in state["requirements"].items()
            if item["investigation"] == "pending"
        ],
        "pending_verifications": [
            req_id for req_id, item in state["requirements"].items()
            if item["verification"] == "pending" and item["investigation"] == "submitted"
        ],
    }


def audit_requirements(workspace: Path) -> Dict[str, Any]:
    _state(workspace)
    return _load_json(workspace / "requirements.json")


def next_action(workspace: Path) -> Dict[str, Any]:
    """Return one deterministic workflow instruction for the thin orchestrator."""
    with _audit_lock(workspace):
        state = _state(workspace)
        if state.get("batch_mode") and (workspace / "batches.json").exists():
            action = _next_batch_action_locked(workspace, state)
        else:
            action = _next_action_locked(workspace, state)
        _save_state(workspace, state)
        return action


def submit_batch_results(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        state = _state(workspace)
        payload = _load_json(payload_path)
        batch_id = str(payload.get("batch_id") or payload.get("batchId") or "")
        active = state.get("active_batch_id")
        if not active or batch_id != active:
            raise ValueError(f"batch submission rejected: active batch is {active}, got {batch_id}")
        batch = _batch_by_id(workspace, batch_id)
        accepted, rejected = _validate_batch_results(workspace, batch, payload.get("results") or [])
        for result in accepted:
            _persist_pack_result(workspace, state, result, reason=result.get("summary") or "batch result submitted")
        _refresh_stage(state)
        _save_state(workspace, state)
        return {
            "accepted": True, "batch_id": batch_id,
            "accepted_results": [{"requirement_id": item["requirement_id"], "status": item["status"]} for item in accepted],
            "rejected_results": rejected,
            "next": "call_audit_next",
        }


def dispatch_result(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    """Validate that a dispatched subagent actually advanced the expected state."""
    with _audit_lock(workspace):
        state = _state(workspace)
        payload = _load_json(payload_path)
        req_id = str(payload.get("requirement_id") or payload.get("requirementId") or "")
        action = str(payload.get("action") or "")
        action_id = str(payload.get("action_id") or payload.get("actionId") or "")
        _require_requirement(state, req_id)
        if action not in {"frame_obligations", "investigate", "review"}:
            raise ValueError("dispatch_result action must be frame_obligations, investigate, or review")
        record = _current_action(workspace, req_id, action, action_id)
        if not record:
            return {
                "dispatch_status": "failed", "reason": "action_not_found",
                "action_id": action_id or None, "requirement_id": req_id, "action": action,
                "recovery_action": "call_audit_next",
            }
        expected_before, expected_after = record["expected_before"], record["expected_after"]
        current_state = _actual_state_for_action(state, req_id, action)
        if record["status"] == "committed":
            return {
                "dispatch_status": "completed", "reason": "already_committed",
                "action_id": record["action_id"], "requirement_id": req_id, "action": action,
                "expected_state": expected_after, "current_state": current_state,
                "next_action": "call_audit_next",
            }
        if record["status"] == "failed_terminal":
            return {
                "dispatch_status": "failed_finalized", "reason": record.get("error") or "state_unchanged",
                "action_id": record["action_id"], "requirement_id": req_id, "action": action,
                "attempt": record["attempt"], "max_attempts": record["max_attempts"],
                "expected_state": expected_after, "current_state": current_state,
                "recovery_action": "terminal_fallback", "next_action": "call_audit_next",
            }
        if record["status"] != "dispatched":
            return {
                "dispatch_status": "failed", "reason": f"action_not_dispatched:{record['status']}",
                "action_id": record["action_id"], "requirement_id": req_id, "action": action,
                "recovery_action": "call_audit_next",
            }
        if current_state == expected_after:
            _update_action(workspace, record["action_id"], status="committed", error="")
            _save_state(workspace, state)
            return {
                "dispatch_status": "completed", "action_id": record["action_id"],
                "requirement_id": req_id, "action": action,
                "expected_state": expected_after, "current_state": current_state,
                "next_action": "call_audit_next",
            }
        if current_state != expected_before:
            raise ValueError(
                f"runtime invariant error: {req_id}:{action} expected {expected_before} or {expected_after}, got {current_state}"
            )
        if int(record["attempt"]) < MAX_SUBAGENT_ATTEMPTS:
            _update_action(workspace, record["action_id"], status="failed", error="state_unchanged")
            retry = _ensure_action(workspace, state, req_id, action, expected_before=expected_before, expected_after=expected_after)
            _save_state(workspace, state)
            return {
                "dispatch_status": "failed", "reason": "state_unchanged",
                "action_id": record["action_id"], "retry_action_id": retry["action_id"],
                "requirement_id": req_id, "action": action, "attempt": record["attempt"],
                "max_attempts": MAX_SUBAGENT_ATTEMPTS,
                "expected_state": expected_after, "current_state": current_state,
                "recovery_action": "retry_same_action", "retry_packet": retry,
            }
        _update_action(workspace, record["action_id"], status="failed_terminal", error="state_unchanged")
        _save_state(workspace, state)
        return {
            "dispatch_status": "failed_finalized", "reason": "state_unchanged",
            "action_id": record["action_id"],
            "requirement_id": req_id, "action": action, "attempt": record["attempt"],
            "max_attempts": MAX_SUBAGENT_ATTEMPTS,
            "expected_state": expected_after, "current_state": current_state,
            "recovery_action": "terminal_fallback",
            "next_action": "call_audit_next",
        }


def frame_obligations(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        state = _state(workspace)
        payload = _load_json(payload_path)
        req_id = str(payload.get("requirement_id") or "")
        _require_requirement(state, req_id)
        if state["requirements"][req_id]["investigation"] == "submitted":
            raise ValueError("submission rejected: investigation is already submitted")
        if state["requirements"][req_id]["investigation"] == "framed":
            existing = _draft_for_requirement(workspace, req_id)
            candidate = _normalize_framed_obligations(workspace, req_id, payload.get("obligations"))
            if candidate == existing["obligations"]:
                return {"accepted": True, "requirement_id": req_id, "obligations": existing["obligations"], "next_step": "investigate"}
            raise ValueError("submission rejected: obligations already framed for this requirement")
        obligations = _normalize_framed_obligations(workspace, req_id, payload.get("obligations"))
        now = _now()
        draft = {
            "requirement_id": req_id, "status": "framed", "obligations": obligations,
            "created_at": now, "updated_at": now,
        }
        _transition(state, req_id, "obligations_framed")
        _upsert(workspace / "investigation-drafts.json", "drafts", req_id, draft)
        _save_state(workspace, state)
        return {"accepted": True, "requirement_id": req_id, "obligations": obligations, "next_step": "investigate"}


def submit_conclusion(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        state = _state(workspace)
        payload = _load_json(payload_path)
        req_id = str(payload.get("requirement_id") or "")
        _require_requirement(state, req_id)
        if state["requirements"][req_id]["investigation"] == "submitted":
            existing = next((item for item in _load_json(workspace / "investigations.json")["investigations"] if item.get("requirement_id") == req_id), None)
            if existing:
                return {"accepted": True, "idempotent": True, "requirement_id": req_id, "next": "call_audit_dispatch_result"}
        if state["requirements"][req_id]["investigation"] == "pending":
            raise ValueError("submission rejected: current investigation phase is pending; call frame_obligations first")
        if state["requirements"][req_id]["investigation"] != "framed":
            raise ValueError(f"submission rejected: current investigation phase is {state['requirements'][req_id]['investigation']}")
        draft = _draft_for_requirement(workspace, req_id)
        conclusion = payload.get("conclusion")
        if conclusion not in {"satisfied", "mismatch", "uncertain"}:
            raise ValueError("conclusion must be satisfied, mismatch, or uncertain")
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            raise ValueError("summary is required")
        requirement = next(item for item in _load_json(workspace / "requirements.json")["requirements"] if item["id"] == req_id)
        obligation_results = _validate_obligation_results(workspace, req_id, draft["obligations"], payload.get("obligation_results") or [])
        mismatch_kind = payload.get("mismatch_kind")
        if conclusion == "mismatch" and mismatch_kind not in {"missing", "partial", "contradiction"}:
            raise ValueError("mismatch requires mismatch_kind: missing, partial, or contradiction")
        negative_checks = payload.get("negative_checks") or []
        if conclusion == "mismatch":
            _validate_negative_checks(req_id, workspace, negative_checks, mismatch_kind)
            _validate_required_checks(req_id, requirement, draft["obligations"], mismatch_kind, negative_checks)
        evidence_ids = sorted({
            evidence_id for result in obligation_results for evidence_id in result.get("evidence_ids", [])
        })
        query_ids = sorted({
            item["query_id"] for item in _jsonl_map(workspace / "queries.jsonl", "query_id").values()
            if item["requirement_id"] == req_id and item["role"] == "investigator"
        })
        if conclusion != "uncertain" and not query_ids:
            raise ValueError("submission rejected: submit_conclusion requires at least one investigator query")
        proposed_status = {"satisfied": "covered", "mismatch": "violated", "uncertain": "unknown"}[conclusion]
        if mismatch_kind == "partial":
            proposed_status = "partial"
        issue = None
        if conclusion == "mismatch":
            issue = {
                "title": str(payload.get("title") or "").strip(),
                "description": summary,
                "match_type": {"missing": "missing_in_code", "partial": "partial_match", "contradiction": "mismatch"}[mismatch_kind],
                "severity": payload.get("severity"), "confidence": payload.get("confidence"),
            }
            _validate_issue(issue)
        canonical = {
            "requirement_id": req_id, "proposed_status": proposed_status, "reasoning": summary,
            "query_ids": query_ids, "evidence_ids": evidence_ids, "counterexample_query_ids": [],
            "claim_scope": "absence" if mismatch_kind == "missing" else "behavior_path",
            "unresolved_questions": payload.get("uncertainties") or [], "issue": issue,
            "agent_conclusion": conclusion, "negative_checks": negative_checks,
            "obligations": draft["obligations"], "obligation_results": obligation_results,
            "findings": obligation_results, "submitted_at": _now(),
        }
        _transition(state, req_id, "investigation_submitted", verification="pending" if conclusion == "mismatch" else "not_required")
        _upsert(workspace / "investigations.json", "investigations", req_id, canonical)
        _save_state(workspace, state)
        return {"accepted": True, "requirement_id": req_id, "conclusion": conclusion, "next": "call_audit_dispatch_result"}


def submit_simple_investigation(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        state = _state(workspace)
        payload = _load_json(payload_path)
        req_id = str(payload.get("requirement_id") or "")
        _require_requirement(state, req_id)
        if state["requirements"][req_id]["investigation"] == "submitted":
            existing = next((item for item in _load_json(workspace / "investigations.json")["investigations"] if item.get("requirement_id") == req_id), None)
            if existing:
                return {"accepted": True, "idempotent": True, "requirement_id": req_id, "next": "call_audit_dispatch_result"}
        conclusion = payload.get("conclusion")
        if conclusion not in {"satisfied", "mismatch", "uncertain"}:
            raise ValueError("conclusion must be satisfied, mismatch, or uncertain")
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            raise ValueError("summary is required")
        queries = [
            item for item in _jsonl_map(workspace / "queries.jsonl", "query_id").values()
            if item["requirement_id"] == req_id and item["role"] == "investigator"
        ]
        if not queries:
            raise ValueError("investigation requires at least one code_search query")
        query_ids = sorted(item["query_id"] for item in queries)
        evidence_map = _jsonl_map(workspace / "evidence.jsonl", "evidence_id")
        evidence_ids = payload.get("evidence_ids") or []
        for evidence_id in evidence_ids:
            evidence = evidence_map.get(evidence_id)
            if not evidence or evidence["requirement_id"] != req_id:
                raise ValueError(f"invalid evidence reference for {req_id}: {evidence_id}")
        if conclusion in {"satisfied", "mismatch"} and not evidence_ids and payload.get("mismatch_kind") != "missing":
            raise ValueError(f"{conclusion} requires code evidence")
        proposed_status = {"satisfied": "covered", "mismatch": "violated", "uncertain": "unknown"}[conclusion]
        mismatch_kind = payload.get("mismatch_kind")
        if conclusion == "mismatch" and mismatch_kind not in {"missing", "partial", "contradiction"}:
            raise ValueError("mismatch requires mismatch_kind: missing, partial, or contradiction")
        if mismatch_kind == "partial":
            proposed_status = "partial"
        issue = None
        if conclusion == "mismatch":
            issue = {
                "title": str(payload.get("title") or "").strip(),
                "description": summary,
                "match_type": {"missing": "missing_in_code", "partial": "partial_match", "contradiction": "mismatch"}[mismatch_kind],
                "severity": payload.get("severity"), "confidence": payload.get("confidence"),
            }
            _validate_issue(issue)
        negative_checks = payload.get("negative_checks") or []
        obligations = payload.get("obligations") or []
        findings = payload.get("findings") or []
        if conclusion == "mismatch":
            _validate_negative_checks(req_id, workspace, negative_checks, mismatch_kind)
            _validate_obligation_findings(workspace, req_id, obligations, findings)
        canonical = {
            "requirement_id": req_id, "proposed_status": proposed_status, "reasoning": summary,
            "query_ids": query_ids, "evidence_ids": evidence_ids, "counterexample_query_ids": [],
            "claim_scope": "absence" if mismatch_kind == "missing" else "behavior_path",
            "unresolved_questions": payload.get("uncertainties") or [], "issue": issue,
            "agent_conclusion": conclusion, "negative_checks": negative_checks,
            "obligations": obligations, "findings": findings, "submitted_at": _now(),
        }
        _transition(state, req_id, "investigation_submitted", verification="pending" if conclusion == "mismatch" else "not_required")
        _upsert(workspace / "investigations.json", "investigations", req_id, canonical)
        _save_state(workspace, state)
        return {"accepted": True, "requirement_id": req_id, "conclusion": conclusion, "next": "call_audit_dispatch_result"}


def review_bundle(workspace: Path, requirement_id: str) -> Dict[str, Any]:
    state = _state(workspace)
    _require_requirement(state, requirement_id)
    investigation = next((item for item in _load_json(workspace / "investigations.json")["investigations"] if item["requirement_id"] == requirement_id), None)
    if not investigation:
        raise ValueError(f"{requirement_id}: investigation is not submitted")
    requirement = next(item for item in _load_json(workspace / "requirements.json")["requirements"] if item["id"] == requirement_id)
    evidence_map = _jsonl_map(workspace / "evidence.jsonl", "evidence_id")
    evidence = [evidence_map[item] for item in investigation.get("evidence_ids", []) if item in evidence_map]
    return {
        "requirement": requirement,
        "requirement_pack": requirement,
        "obligations": investigation.get("obligations") or [],
        "obligation_results": investigation.get("obligation_results") or investigation.get("findings") or [],
        "negative_checks": investigation.get("negative_checks") or [],
        "claim": {
            "conclusion": investigation.get("agent_conclusion"), "status": investigation["proposed_status"],
            "summary": investigation["reasoning"], "issue": investigation.get("issue"),
            "obligations": investigation.get("obligations") or [],
            "findings": investigation.get("obligation_results") or investigation.get("findings") or [],
        },
        "evidence": evidence,
        "search_summary": {
            "query_count": len(investigation.get("query_ids", [])),
            "limitations": [item.get("limitation") for item in _jsonl_map(workspace / "queries.jsonl", "query_id").values() if item["query_id"] in investigation.get("query_ids", []) and item.get("limitation")],
        },
    }


def submit_simple_review(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        state = _state(workspace)
        payload = _load_json(payload_path)
        req_id = str(payload.get("requirement_id") or "")
        _require_requirement(state, req_id)
        if state["requirements"][req_id]["verification"] == "submitted":
            existing = next((item for item in _load_json(workspace / "verifications.json")["verifications"] if item.get("requirement_id") == req_id), None)
            if existing:
                return {"accepted": True, "idempotent": True, "requirement_id": req_id, "next": "call_audit_dispatch_result"}
        if state["requirements"][req_id]["verification"] != "pending":
            raise ValueError(f"{req_id}: review is not pending")
        verdict = payload.get("verdict")
        if verdict not in {"accept", "reject", "uncertain"}:
            raise ValueError("verdict must be accept, reject, or uncertain")
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise ValueError("review reason is required")
        canonical = {
            "requirement_id": req_id,
            "verdict": "accepted" if verdict == "accept" else ("rejected" if verdict == "reject" else "needs_more_work"),
            "reasoning": reason, "query_ids": [], "evidence_ids": [],
            "challenges": payload.get("unsupported_claims") or [], "recommended_status": None,
            "lightweight_review": True, "submitted_at": _now(),
        }
        _transition(state, req_id, "review_submitted")
        _upsert(workspace / "verifications.json", "verifications", req_id, canonical)
        _save_state(workspace, state)
        return {"accepted": True, "requirement_id": req_id, "verdict": verdict, "next": "call_audit_dispatch_result"}


def finish_audit(workspace: Path) -> Dict[str, Any]:
    state = _state(workspace)
    output = state.get("requested_output")
    if not output:
        raise ValueError("audit was initialized without an output path")
    if not state.get("assembly_allowed"):
        raise ValueError("state invariant error: audit_finish called before audit_next returned finish")
    return assemble_result(workspace, Path(output))


def verification_context(workspace: Path, requirement_id: str) -> Dict[str, Any]:
    state = _state(workspace)
    _require_requirement(state, requirement_id)
    requirement = next(
        item for item in _load_json(workspace / "requirements.json")["requirements"]
        if item["id"] == requirement_id
    )
    queries = [
        item for item in _jsonl_map(workspace / "queries.jsonl", "query_id").values()
        if item["requirement_id"] == requirement_id and item["role"] == "investigator"
    ]
    evidence = [
        item for item in _jsonl_map(workspace / "evidence.jsonl", "evidence_id").values()
        if item["requirement_id"] == requirement_id
        and item.get("query_id") in {query["query_id"] for query in queries}
    ]
    return {
        "requirement": requirement,
        "raw_investigator_queries": sorted(queries, key=lambda item: item["query_id"]),
        "raw_evidence": sorted(evidence, key=lambda item: item["evidence_id"]),
        "excluded": ["investigator proposed_status", "investigator reasoning", "investigator issue draft"],
        "instruction": "Run verifier-owned queries before submitting a verdict.",
    }


def verification_conclusion_context(workspace: Path, requirement_id: str) -> Dict[str, Any]:
    state = _state(workspace)
    _require_requirement(state, requirement_id)
    verifier_queries = [
        item for item in _jsonl_map(workspace / "queries.jsonl", "query_id").values()
        if item["requirement_id"] == requirement_id and item["role"] == "verifier"
    ]
    if not verifier_queries:
        raise ValueError("run at least one verifier-owned query before viewing the investigation conclusion")
    investigation = next(
        (item for item in _load_json(workspace / "investigations.json")["investigations"]
         if item["requirement_id"] == requirement_id),
        None,
    )
    if not investigation:
        raise ValueError(f"{requirement_id}: investigation is not submitted")
    return {"requirement_id": requirement_id, "investigation": investigation}


def code_query(
    workspace: Path, requirement_id: str = "", role: str = "investigator", mode: str = "", query: str = "",
    path: str = "", start: int = 1, end: int = 200, limit: int = 50,
) -> Dict[str, Any]:
    with _audit_lock(workspace):
        return _code_query(
            workspace, requirement_id, role, mode, query=query, path=path, start=start, end=end, limit=limit
        )


def _code_query(
    workspace: Path, requirement_id: str = "", role: str = "investigator", mode: str = "", query: str = "",
    path: str = "", start: int = 1, end: int = 200, limit: int = 50,
) -> Dict[str, Any]:
    state = _state(workspace)
    query_scope = _query_scope(workspace, state, requirement_id, role)
    if role not in {"investigator", "verifier"}:
        raise ValueError("role must be investigator or verifier")
    if (
        query_scope["kind"] == "requirement"
        and role == "investigator"
        and state["requirements"][requirement_id]["investigation"] == "pending"
        and not _requirement_in_active_batch(workspace, state, requirement_id)
    ):
        raise ValueError("code_search rejected: current investigation phase is pending; call frame_obligations first")
    if query_scope["kind"] == "requirement" and role == "investigator" and state["requirements"][requirement_id]["investigation"] == "submitted":
        raise ValueError("code_search rejected: investigation is already submitted")
    requested_mode = mode
    mode = QUERY_MODE_ALIASES.get(mode.lower(), mode.lower())
    if mode not in {"concept", "source", "repo_map", "component", "build", "symbol", "references", "callers", "callees", "path", "data_flow"}:
        raise ValueError(f"unsupported query mode: {mode}")
    _enforce_batch_query_budget(workspace, query_scope, role, mode)
    repo = Path(state["repo"])
    results: List[Dict[str, Any]] = []
    tool_status = "completed"
    limitation = ""
    coverage = _coverage_context(workspace, repo)
    if mode == "concept":
        results = _rg_query(repo, query, limit)
        limitation = "text search only; no symbol/reference/call semantics"
    elif mode == "source":
        files = load_files(workspace / "code-index")
        results = _source_query(repo, files, path, start, end)
    elif mode in {"component", "build", "symbol", "references", "callers", "callees", "repo_map"}:
        results, metadata = query_codefacts(
            workspace / "code-index" / "codefacts.sqlite", mode, query=query, path=path,
            start=start, end=end, limit=limit,
        )
        tool_status = metadata.get("status", "completed")
        limitation = metadata.get("detail", "")
        coverage.update(metadata.get("coverage") or {})
    else:
        tool_status = "tool_limited"
        limitation = f"{mode} requires the later AST/SCIP/CodeQL index layer"
    record_requirement_id = query_scope.get("batch_id") or requirement_id
    query_record = _record_query(
        workspace, state, record_requirement_id, role, mode,
        {"query": query, "path": path, "start": start, "end": end, "limit": limit,
         "requested_mode": requested_mode, "requested_requirement_id": requirement_id},
        [_materialize_result(repo, item) for item in results], tool_status, limitation,
        coverage=coverage, batch_id=query_scope.get("batch_id"),
    )
    return query_record


def _query_scope(workspace: Path, state: Dict[str, Any], requirement_id: str, role: str) -> Dict[str, Any]:
    if requirement_id and requirement_id in state["requirements"]:
        return {"kind": "requirement", "requirement_id": requirement_id}
    active_batch = state.get("active_batch_id")
    if role == "investigator" and active_batch:
        batch = _batch_by_id(workspace, active_batch)
        return {
            "kind": "batch", "batch_id": active_batch,
            "requirement_ids": batch["requirement_ids"],
            "requested_requirement_id": requirement_id,
        }
    _require_requirement(state, requirement_id)
    return {"kind": "requirement", "requirement_id": requirement_id}


def _enforce_batch_query_budget(workspace: Path, query_scope: Dict[str, Any], role: str, mode: str) -> None:
    batch_id = query_scope.get("batch_id")
    if role != "investigator" or not batch_id:
        return
    queries_path = workspace / "queries.jsonl"
    rows = []
    if queries_path.exists():
        rows = [json.loads(line) for line in queries_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    batch_queries = [item for item in rows if item.get("batch_id") == batch_id]
    text_queries = [item for item in batch_queries if item.get("mode") == "concept"]
    if len(batch_queries) >= MAX_BATCH_QUERIES:
        raise ValueError(
            f"batch query budget exceeded for {batch_id}: max {MAX_BATCH_QUERIES}. "
            "Submit results from existing evidence and mark undecidable Packs unknown."
        )
    if mode == "concept" and len(text_queries) >= MAX_BATCH_TEXT_QUERIES:
        raise ValueError(
            f"batch text query budget exceeded for {batch_id}: max {MAX_BATCH_TEXT_QUERIES}. "
            "Use symbol/source navigation or submit unknown for unresolved Packs."
        )


def submit_investigation(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        return _submit_investigation(workspace, payload_path)


def _submit_investigation(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    state = _state(workspace)
    payload = _load_json(payload_path)
    req_id = str(payload.get("requirement_id") or "")
    _require_requirement(state, req_id)
    _validate_submission_refs(workspace, req_id, "investigator", payload)
    status = payload.get("proposed_status")
    status = {
        "no_mismatch": "covered",
        "mismatch_candidate": "violated",
        "insufficient_evidence": "unknown",
    }.get(status, status)
    if status not in INVESTIGATION_STATUSES:
        raise ValueError(f"invalid proposed_status: {status}")
    if not payload.get("reasoning"):
        raise ValueError("investigation reasoning is required")
    claim_scope = payload.get("claim_scope") or "behavior_path"
    if claim_scope not in {"local_fact", "behavior_path", "all_paths", "absence"}:
        raise ValueError(f"invalid claim_scope: {claim_scope}")
    query_ids = payload.get("query_ids") or []
    if status in {"covered", "violated", "partial", "no_evidence_found"} and not query_ids:
        raise ValueError(f"{status} investigation requires query_ids")
    if status in {"covered", "violated", "partial"} and not payload.get("evidence_ids"):
        raise ValueError(f"{status} investigation requires evidence_ids")
    if status == "covered" and not payload.get("counterexample_query_ids"):
        raise ValueError("covered investigation requires counterexample_query_ids")
    issue = payload.get("issue")
    if status in {"violated", "partial"}:
        _validate_issue(issue)
        _validate_negative_checks(req_id, workspace, payload.get("negative_checks") or [], "partial" if status == "partial" else "contradiction")
    canonical = {
        "requirement_id": req_id, "proposed_status": status, "reasoning": payload["reasoning"],
        "query_ids": query_ids, "evidence_ids": payload.get("evidence_ids") or [],
        "counterexample_query_ids": payload.get("counterexample_query_ids") or [], "claim_scope": claim_scope,
        "unresolved_questions": payload.get("unresolved_questions") or [],
        "applicability": payload.get("applicability"),
        "implementation_obligations": payload.get("implementation_obligations") or [],
        "code_findings": payload.get("code_findings") or [],
        "negative_checks": payload.get("negative_checks") or [],
        "mismatch": payload.get("mismatch"),
        "issue": issue if status in {"violated", "partial"} else None,
        "submitted_at": _now(),
    }
    _transition(state, req_id, "investigation_submitted", verification="pending" if _verification_required(workspace, canonical) else "not_required")
    _upsert(workspace / "investigations.json", "investigations", req_id, canonical)
    _save_state(workspace, state)
    return {"accepted": True, "requirement_id": req_id, "status": status, "audit": audit_status(workspace)}


def submit_verification(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        return _submit_verification(workspace, payload_path)


def _submit_verification(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    state = _state(workspace)
    payload = _load_json(payload_path)
    req_id = str(payload.get("requirement_id") or "")
    _require_requirement(state, req_id)
    if state["requirements"][req_id]["verification"] == "submitted":
        existing = next((item for item in _load_json(workspace / "verifications.json")["verifications"] if item.get("requirement_id") == req_id), None)
        if existing:
            return {"accepted": True, "idempotent": True, "requirement_id": req_id, "audit": audit_status(workspace)}
    if state["requirements"][req_id]["investigation"] != "submitted":
        raise ValueError(f"{req_id}: investigation must be submitted before verification")
    _validate_submission_refs(workspace, req_id, "verifier", payload)
    verdict = payload.get("verdict")
    if verdict not in VERIFICATION_VERDICTS:
        raise ValueError(f"invalid verdict: {verdict}")
    if not payload.get("reasoning"):
        raise ValueError("verification reasoning is required")
    if verdict == "accepted" and not payload.get("query_ids"):
        raise ValueError("accepted verification requires at least one verifier query")
    recommended_status = payload.get("recommended_status")
    if recommended_status is not None and recommended_status not in INVESTIGATION_STATUSES:
        raise ValueError(f"invalid recommended_status: {recommended_status}")
    challenges = payload.get("challenges") or []
    if not isinstance(challenges, list):
        raise ValueError("verification challenges must be an array")
    for challenge in challenges:
        _validate_verification_check(challenge)
    canonical = {
        "requirement_id": req_id, "verdict": verdict, "reasoning": payload["reasoning"],
        "query_ids": payload.get("query_ids") or [], "evidence_ids": payload.get("evidence_ids") or [],
        "challenges": challenges,
        "recommended_status": recommended_status, "submitted_at": _now(),
    }
    _transition(state, req_id, "review_submitted")
    _upsert(workspace / "verifications.json", "verifications", req_id, canonical)
    _save_state(workspace, state)
    return {"accepted": True, "requirement_id": req_id, "verdict": verdict, "audit": audit_status(workspace)}


def assemble_result(workspace: Path, out: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        return _assemble_result(workspace, out)


def _assemble_result(workspace: Path, out: Path) -> Dict[str, Any]:
    state = _state(workspace)
    if not state["assembly_allowed"]:
        raise ValueError("assembly is blocked until every requirement has investigation and verification")
    requirements = _load_json(workspace / "requirements.json")["requirements"]
    investigations = {item["requirement_id"]: item for item in _load_json(workspace / "investigations.json")["investigations"]}
    verifications = {item["requirement_id"]: item for item in _load_json(workspace / "verifications.json")["verifications"]}
    records, issues, unverified = [], [], []
    evidence_map = _jsonl_map(workspace / "evidence.jsonl", "evidence_id")
    for req in requirements:
        req_id = req["id"]
        investigation = investigations[req_id]
        verification = verifications.get(req_id) or {
            "requirement_id": req_id, "verdict": "not_required",
            "reasoning": "Low-risk local fact accepted by deterministic evidence checks.",
            "query_ids": [], "evidence_ids": [], "challenges": [],
        }
        verification_ok = verification["verdict"] in {"accepted", "not_required"}
        status = investigation["proposed_status"] if verification_ok else "unknown"
        if verification.get("recommended_status") in INVESTIGATION_STATUSES and verification["verdict"] == "accepted":
            status = verification["recommended_status"]
        record = {
            "requirement": req, "status": status,
            "investigation": investigation, "verification": verification,
        }
        records.append(record)
        if status in {"violated", "partial"} and verification_ok and investigation.get("issue"):
            issues.append(_assemble_issue(len(issues) + 1, req, investigation, verification, evidence_map))
        if status in {"unknown", "no_evidence_found", "non_verifiable"} or not verification_ok:
            reason = verification["reasoning"] if not verification_ok else investigation.get("reasoning")
            unverified.append({"requirement_id": req_id, "status": status, "reason": reason})
    counts = Counter(item["status"] for item in records)
    payload = {
        "tool": "specdiff", "schema_version": "2.0", "artifact_type": "assembled_audit",
        "audit_id": state["audit_id"], "repo": state["repo"], "audit_workspace": str(workspace.resolve()),
        "code_index": load_repository(workspace / "code-index"),
        "coverage_summary": {"requirements_total": len(records), "status_counts": dict(sorted(counts.items()))},
        "requirements": records, "unverified_requirements": unverified, "issues": issues,
        "pack_coverage": _pack_coverage(workspace, records, verifications),
        "audit_state": {"stage": "assembled", "requirements_sha256": state["requirements_sha256"]},
    }
    competition_payload = _competition_output(payload)
    _write_json(out, competition_payload)
    full_out = out.with_suffix(".full.json")
    _write_json(full_out, payload)
    sarif_out = out.with_suffix(".sarif")
    _write_sarif(sarif_out, payload)
    state["stage"] = "assembled"
    state["assembled_output"] = str(out.resolve())
    state["assembled_full_report"] = str(full_out.resolve())
    _save_state(workspace, state)
    return {
        "assembled": True, "out": str(out.resolve()), "full_report": str(full_out.resolve()),
        "sarif": str(sarif_out.resolve()), "issues": len(issues), "status_counts": dict(counts),
    }


def _competition_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"issues": [_competition_issue(issue) for issue in payload.get("issues", [])]}


def _competition_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    spec = issue.get("spec_evidence") or {}
    code = _primary_code_evidence(issue)
    return {
        "id": issue.get("id"),
        "title": issue.get("title") or "Specification/code inconsistency",
        "rfc_reference": _rfc_reference(spec),
        "violation_level": _violation_level(issue, spec),
        "file": code.get("path"),
        "line": code.get("line") or code.get("start_line"),
        "evidence": {
            "code_snippet": code.get("quote") or "",
            "rfc_requirement": spec.get("quote") or "",
        },
    }


def _primary_code_evidence(issue: Dict[str, Any]) -> Dict[str, Any]:
    evidence = issue.get("code_evidence") or []
    if not evidence:
        return {}
    exact = [item for item in evidence if item.get("precision") in {"exact_source", "exact_source_span", "compiler_precise"}]
    rows = exact or evidence
    rows = sorted(
        rows,
        key=lambda item: (
            0 if item.get("path") else 1,
            int(item.get("line") or item.get("start_line") or 10**9),
            str(item.get("evidence_id") or ""),
        ),
    )
    return rows[0]


def _rfc_reference(spec: Dict[str, Any]) -> str:
    document = str(spec.get("document") or "unknown").strip()
    section = str(spec.get("section") or "").strip()
    if section and section.lower() != "unknown":
        return f"{document} §{section}"
    return document


def _violation_level(issue: Dict[str, Any], spec: Dict[str, Any]) -> str:
    haystack = " ".join(
        str(value or "") for value in (
            issue.get("description"), issue.get("title"), spec.get("quote"), spec.get("section")
        )
    ).upper()
    for level in ("MUST NOT", "SHOULD NOT", "MUST", "SHOULD", "MAY"):
        if re.search(rf"\b{re.escape(level)}\b", haystack):
            return level
    severity = str(issue.get("severity") or "").lower()
    if severity in {"critical", "high"}:
        return "MUST"
    if severity == "medium":
        return "SHOULD"
    return "MAY"


def _normalize_requirements(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = payload.get("requirement_packs") or payload.get("packs") or payload.get("requirements")
    if not isinstance(rows, list):
        raise ValueError("requirements JSON must contain a requirements, packs, or requirement_packs list")
    result, seen = [], set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"requirement {index} is not an object")
        req_id = str(row.get("id") or row.get("pack_id") or f"REQ-{index:04d}")
        if req_id in seen: raise ValueError(f"duplicate requirement id: {req_id}")
        quote = row.get("quote") or (row.get("source") or {}).get("quote")
        normalized = row.get("normalized") or (row.get("source") or {}).get("normalized") or quote
        if not quote or not normalized: raise ValueError(f"{req_id}: quote and normalized requirement are required")
        normalized_row = {
            "id": req_id, "document": row.get("document") or (row.get("source") or {}).get("document"),
            "section": row.get("section") or (row.get("source") or {}).get("section") or "unknown",
            "quote": quote, "normalized": normalized, "keywords": row.get("keywords") or [],
            "source": row.get("source") if isinstance(row.get("source"), str) else (row.get("source") or {}).get("source_kind", "document"),
        }
        for field in (
            "pack_type", "seed_clause_ids", "clause_ids", "relation_ids", "document_ids", "sections",
            "normative_levels", "normative_strength", "candidate_kind", "status", "clauses",
            "capability", "scope_source", "responsibility_status",
        ):
            if field in row:
                normalized_row[field] = row[field]
        result.append(normalized_row)
        seen.add(req_id)
    return result


def _rg_query(repo: Path, query: str, limit: int) -> List[Dict[str, Any]]:
    if not query.strip():
        return []
    try:
        result = subprocess.run(
            ["rg", "--json", "--ignore-case", "--max-count", str(limit), query, str(repo)],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        return _python_text_query(repo, query, limit)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"text query failed: {exc}") from exc
    rows: List[Dict[str, Any]] = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") != "match":
            continue
        data = item["data"]
        raw_path = Path(data["path"]["text"])
        try:
            path = str(raw_path.resolve().relative_to(repo.resolve()))
        except ValueError:
            continue
        rows.append({
            "path": path, "line": data["line_number"],
            "quote": data["lines"]["text"].strip()[:500], "backend": "ripgrep",
            "precision": "text",
        })
        if len(rows) >= limit:
            break
    return rows


def _python_text_query(repo: Path, query: str, limit: int) -> List[Dict[str, Any]]:
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
    rows: List[Dict[str, Any]] = []
    skip_dirs = {".git", ".specdiff", "node_modules", ".venv", "venv", "__pycache__", "dist"}
    for path in sorted(repo.rglob("*")):
        if len(rows) >= limit:
            break
        if not path.is_file():
            continue
        rel_parts = path.relative_to(repo).parts
        if any(part in skip_dirs for part in rel_parts):
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = str(path.relative_to(repo))
        for line_number, line in enumerate(lines, 1):
            if pattern.search(line):
                rows.append({
                    "path": rel, "line": line_number,
                    "quote": line.strip()[:500], "backend": "python_text_search",
                    "precision": "text_fallback",
                })
                if len(rows) >= limit:
                    break
    return rows


def _source_query(repo: Path, files: List[Dict[str, Any]], path: str, start: int, end: int) -> List[Dict[str, Any]]:
    rel_path = _indexed_source_path(repo, files, path)
    item = next((row for row in files if row["path"] == rel_path), None)
    if not item: raise ValueError(f"path is not indexed: {path}")
    lines = (repo / rel_path).read_text(encoding="utf-8", errors="replace").splitlines()
    start, end = max(1, start), min(len(lines), max(start, end))
    quote = "\n".join(lines[start - 1:end])[:4000]
    return [{
        "file_id": item["file_id"], "path": rel_path, "line": start,
        "start_line": start, "end_line": end, "quote": quote,
        "backend": "source_read", "precision": "exact_source_span",
    }]


def _indexed_source_path(repo: Path, files: List[Dict[str, Any]], raw_path: str) -> str:
    if not raw_path:
        raise ValueError("source query requires path")
    indexed = {str(row["path"]).replace("\\", "/"): str(row["path"]).replace("\\", "/") for row in files}
    indexed_lower = {path.lower(): path for path in indexed.values()}
    raw = str(raw_path).strip().strip('"').strip("'").replace("\\", "/")
    repo_norm = str(repo.resolve()).replace("\\", "/").rstrip("/")
    candidates = []
    if raw.startswith(repo_norm + "/"):
        candidates.append(raw[len(repo_norm) + 1:])
    candidates.extend([raw, raw.lstrip("./")])
    for candidate in candidates:
        candidate = candidate.replace("\\", "/").lstrip("./")
        if candidate in indexed:
            return indexed[candidate]
        if candidate.lower() in indexed_lower:
            return indexed_lower[candidate.lower()]
    raw_lower = raw.lower().rstrip("/")
    matches = [
        indexed_path for indexed_path in indexed.values()
        if raw_lower.endswith("/" + indexed_path.lower()) or raw_lower == indexed_path.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"source path is ambiguous: {raw_path}")
    raise ValueError(f"path is not indexed: {raw_path}")


def _materialize_result(repo: Path, item: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(item)
    line = result.get("line") or result.get("start_line")
    path = result.get("path")
    if path and line and not result.get("quote"):
        try:
            lines = (repo / path).read_text(encoding="utf-8", errors="replace").splitlines()
            result["line"] = int(line)
            result["quote"] = lines[int(line) - 1].strip()[:500]
        except (OSError, IndexError, ValueError):
            pass
    return result


def _record_query(
    workspace: Path, state: Dict[str, Any], req_id: str, role: str, mode: str,
    parameters: Dict[str, Any], results: List[Dict[str, Any]], tool_status: str,
    limitation: str, coverage: Optional[Dict[str, Any]] = None,
    batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    state["counters"]["query"] += 1
    query_id = f"Q-{state['counters']['query']:07d}"
    evidence_ids = []
    with (workspace / "evidence.jsonl").open("a", encoding="utf-8") as evidence_file:
        for result in results:
            if "path" not in result or ("line" not in result and "start_line" not in result): continue
            state["counters"]["evidence"] += 1
            evidence_id = f"E-{state['counters']['evidence']:08d}"
            evidence = {"evidence_id": evidence_id, "query_id": query_id, "requirement_id": req_id, **result}
            if batch_id:
                evidence["batch_id"] = batch_id
            evidence_file.write(json.dumps(evidence, ensure_ascii=False) + "\n")
            evidence_ids.append(evidence_id)
    record = {"query_id": query_id, "requirement_id": req_id, "role": role, "mode": mode, "parameters": parameters, "status": tool_status, "limitation": limitation, "coverage": coverage or {}, "result_count": len(results), "evidence_ids": evidence_ids, "created_at": _now()}
    if batch_id:
        record["batch_id"] = batch_id
    with (workspace / "queries.jsonl").open("a", encoding="utf-8") as query_file:
        query_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    _save_state(workspace, state)
    return record


def _validate_submission_refs(workspace: Path, req_id: str, role: str, payload: Dict[str, Any]) -> None:
    queries = _jsonl_map(workspace / "queries.jsonl", "query_id")
    evidence = _jsonl_map(workspace / "evidence.jsonl", "evidence_id")
    all_query_ids = list(payload.get("query_ids") or []) + list(payload.get("counterexample_query_ids") or [])
    for query_id in all_query_ids:
        item = queries.get(query_id)
        if not item or item["requirement_id"] != req_id or item["role"] != role:
            raise ValueError(f"invalid {role} query reference for {req_id}: {query_id}")
    for evidence_id in payload.get("evidence_ids") or []:
        item = evidence.get(evidence_id)
        if not item or item["requirement_id"] != req_id:
            raise ValueError(f"invalid evidence reference for {req_id}: {evidence_id}")


def _validate_issue(issue: Any) -> None:
    if not isinstance(issue, dict):
        raise ValueError("violated or partial investigation requires an issue object")
    for field in ("title", "description"):
        if not isinstance(issue.get(field), str) or not issue[field].strip():
            raise ValueError(f"issue {field} is required")
    if issue.get("match_type") not in {
        "missing_in_code", "partial_match", "mismatch", "code_weaker_than_spec",
        "undocumented_extra_behavior", "spec_conflict",
    }:
        raise ValueError("invalid issue match_type")
    if issue.get("severity") not in {"critical", "high", "medium", "low"}:
        raise ValueError("invalid issue severity")
    confidence = issue.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("issue confidence must be between 0 and 1")


def _validate_negative_checks(req_id: str, workspace: Path, checks: Any, mismatch_kind: Optional[str]) -> None:
    if not isinstance(checks, list):
        raise ValueError("negative_checks must be an array")
    dimensions = {str(item.get("dimension")) for item in checks if isinstance(item, dict)}
    requirement = next(item for item in _load_json(workspace / "requirements.json")["requirements"] if item["id"] == req_id)
    pack_type = requirement.get("pack_type")
    required = {"alternative_implementation"}
    if pack_type == "capability_presence" or mismatch_kind == "missing":
        required = {"symbol_or_file_search", "alternative_naming", "build_or_configuration", "responsibility"}
    missing = sorted(required - dimensions)
    if missing:
        raise ValueError(f"mismatch investigation missing negative check dimensions: {', '.join(missing)}")
    for item in checks:
        if not isinstance(item, dict):
            raise ValueError("negative_checks entries must be objects")
        if item.get("status") not in {"searched", "not_applicable", "inconclusive"}:
            raise ValueError("negative_checks status must be searched, not_applicable, or inconclusive")
        result = str(item.get("result") or "").strip()
        if not result:
            raise ValueError(f"negative check {item.get('dimension')}: result is required")
        query_ids = item.get("query_ids") or []
        if item.get("status") == "searched" and not query_ids:
            raise ValueError(f"negative check {item.get('dimension')}: status=searched requires query_ids")
        for query_id in query_ids:
            query = _jsonl_map(workspace / "queries.jsonl", "query_id").get(query_id)
            if not query or query["requirement_id"] != req_id or query["role"] != "investigator":
                raise ValueError(f"negative check {item.get('dimension')}: invalid investigator query_id {query_id}")


def required_checks(requirement: Dict[str, Any], obligations: List[Dict[str, Any]], mismatch_kind: Optional[str] = None) -> List[str]:
    if requirement.get("pack_type") == "capability_presence" or mismatch_kind == "missing":
        return ["symbol_or_file_search", "alternative_naming", "build_or_configuration", "responsibility"]
    return ["alternative_implementation"]


def _validate_required_checks(
    req_id: str, requirement: Dict[str, Any], obligations: List[Dict[str, Any]],
    mismatch_kind: Optional[str], checks: List[Dict[str, Any]],
) -> None:
    dimensions = {str(item.get("dimension")) for item in checks if isinstance(item, dict)}
    missing = sorted(set(required_checks(requirement, obligations, mismatch_kind)) - dimensions)
    if missing:
        raise ValueError(f"submission rejected: missing required checks: {', '.join(missing)}")


def _normalize_framed_obligations(workspace: Path, req_id: str, rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("frame_obligations requires a non-empty obligations array")
    if len(rows) > 3:
        raise ValueError("frame_obligations accepts at most 3 obligations")
    requirement = next(item for item in _load_json(workspace / "requirements.json")["requirements"] if item["id"] == req_id)
    pack_clause_ids = set(requirement.get("clause_ids") or [])
    is_capability = requirement.get("pack_type") == "capability_presence"
    allowed_source_ids = pack_clause_ids or {req_id}
    obligations = []
    seen_ids = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"obligations[{index - 1}] must be an object")
        description = str(row.get("description") or "").strip()
        if not description:
            raise ValueError(f"obligations[{index - 1}].description is required")
        source_clause_ids = row.get("source_clause_ids")
        if source_clause_ids is None:
            source_clause_ids = row.get("sourceClauseIds")
        source_clause_ids = source_clause_ids or []
        if not isinstance(source_clause_ids, list) or not all(isinstance(item, str) for item in source_clause_ids):
            raise ValueError(f"obligations[{index - 1}].source_clause_ids must be a string array")
        if not source_clause_ids and not is_capability:
            raise ValueError(f"obligations[{index - 1}].source_clause_ids are required")
        if source_clause_ids and not set(source_clause_ids).issubset(allowed_source_ids):
            raise ValueError(f"obligations[{index - 1}].source_clause_ids must belong to the current Requirement Pack")
        obligation_id = _obligation_id(req_id, description, source_clause_ids)
        if obligation_id in seen_ids:
            raise ValueError(f"duplicate framed obligation: {obligation_id}")
        seen_ids.add(obligation_id)
        obligations.append({
            "id": obligation_id,
            "description": description,
            "source_clause_ids": sorted(source_clause_ids),
        })
    return obligations


def _validate_obligation_results(workspace: Path, req_id: str, obligations: List[Dict[str, Any]], rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("obligation_results must be an array")
    expected = {item["id"] for item in obligations}
    seen = set()
    evidence_map = _jsonl_map(workspace / "evidence.jsonl", "evidence_id")
    results = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"obligation_results[{index - 1}] must be an object")
        obligation_id = str(row.get("obligation_id") or row.get("obligationId") or "").strip()
        if obligation_id not in expected:
            raise ValueError(f"submission rejected: unknown obligation id {obligation_id}")
        if obligation_id in seen:
            raise ValueError(f"submission rejected: duplicate obligation result for {obligation_id}")
        seen.add(obligation_id)
        status = row.get("status")
        if status not in {"supported", "contradicted", "partial", "not_found"}:
            raise ValueError("obligation result status must be supported, contradicted, partial, or not_found")
        evidence_ids = row.get("evidence_ids")
        if evidence_ids is None:
            evidence_ids = row.get("evidenceIds")
        evidence_ids = evidence_ids or []
        if status in {"supported", "contradicted", "partial"} and not evidence_ids:
            raise ValueError(f"submission rejected: {obligation_id} result {status} requires evidence_ids")
        for evidence_id in evidence_ids:
            evidence = evidence_map.get(evidence_id)
            if not evidence or evidence["requirement_id"] != req_id:
                raise ValueError(f"submission rejected: {obligation_id} has invalid evidence_id {evidence_id}")
        results.append({"obligation_id": obligation_id, "status": status, "evidence_ids": evidence_ids})
    missing = sorted(expected - seen)
    if missing:
        raise ValueError(f"submission rejected: missing obligation result for {', '.join(missing)}")
    return sorted(results, key=lambda item: item["obligation_id"])


def _draft_for_requirement(workspace: Path, req_id: str) -> Dict[str, Any]:
    drafts_path = workspace / "investigation-drafts.json"
    payload = _load_json(drafts_path) if drafts_path.exists() else {"schema_version": "1.0", "drafts": []}
    draft = next((item for item in payload.get("drafts", []) if item.get("requirement_id") == req_id), None)
    if not draft:
        raise ValueError(f"no framed obligations found for {req_id}")
    return draft


def _obligation_id(req_id: str, description: str, source_clause_ids: List[str]) -> str:
    normalized = re.sub(r"\s+", " ", description.strip().lower())
    digest = hashlib.sha256(
        json.dumps([req_id, normalized, sorted(source_clause_ids)], sort_keys=True).encode("utf-8")
    ).hexdigest()[:8].upper()
    return f"OBL-{digest}"


def _spec_evidence_for_issue(req: Dict[str, Any], investigation: Dict[str, Any]) -> List[Dict[str, Any]]:
    obligations = {item["id"]: item for item in investigation.get("obligations", [])}
    clause_ids = []
    for result in investigation.get("obligation_results") or investigation.get("findings") or []:
        if result.get("status") not in {"contradicted", "partial", "not_found"}:
            continue
        obligation = obligations.get(result.get("obligation_id"))
        if not obligation:
            continue
        clause_ids.extend(obligation.get("source_clause_ids") or [])
    clause_ids = sorted(set(clause_ids))
    clause_map = {item.get("id"): item for item in req.get("clauses", []) if isinstance(item, dict)}
    rows = []
    for clause_id in clause_ids:
        clause = clause_map.get(clause_id)
        if clause:
            rows.append({
                "clause_id": clause_id,
                "document": clause.get("document") or clause.get("document_id") or req.get("document"),
                "section": clause.get("section") or req.get("section"),
                "quote": clause.get("quote") or clause.get("text") or req.get("quote"),
            })
        else:
            rows.append({
                "clause_id": clause_id,
                "document": req.get("document"),
                "section": req.get("section"),
                "quote": req.get("quote"),
            })
    if rows:
        return rows
    return [{"document": req.get("document"), "section": req.get("section"), "quote": req.get("quote")}]


def _validate_obligation_findings(workspace: Path, req_id: str, obligations: Any, findings: Any) -> None:
    if not isinstance(obligations, list) or not obligations:
        raise ValueError("mismatch investigation requires non-empty obligations")
    if not isinstance(findings, list) or not findings:
        raise ValueError("mismatch investigation requires non-empty findings")
    requirement = next(item for item in _load_json(workspace / "requirements.json")["requirements"] if item["id"] == req_id)
    pack_clause_ids = set(requirement.get("clause_ids") or [])
    obligation_ids = set()
    evidence_map = _jsonl_map(workspace / "evidence.jsonl", "evidence_id")
    for obligation in obligations:
        if not isinstance(obligation, dict):
            raise ValueError("obligations entries must be objects")
        obligation_id = str(obligation.get("id") or "").strip()
        if not obligation_id:
            raise ValueError("obligations require id")
        if obligation_id in obligation_ids:
            raise ValueError(f"duplicate obligation id: {obligation_id}")
        obligation_ids.add(obligation_id)
        description = str(obligation.get("description") or "").strip()
        if not description:
            raise ValueError(f"{obligation_id}: obligation description is required")
        source_clause_ids = obligation.get("source_clause_ids") or []
        if not isinstance(source_clause_ids, list) or not source_clause_ids:
            raise ValueError(f"{obligation_id}: source_clause_ids are required")
        if pack_clause_ids and not set(source_clause_ids).issubset(pack_clause_ids):
            raise ValueError(f"{obligation_id}: source_clause_ids must belong to the current requirement pack")
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("findings entries must be objects")
        obligation_id = str(finding.get("obligation_id") or "").strip()
        if obligation_id not in obligation_ids:
            raise ValueError(f"finding references unknown obligation_id: {obligation_id}")
        status = finding.get("status")
        if status not in {"supported", "contradicted", "partial", "not_found"}:
            raise ValueError("findings status must be supported, contradicted, partial, or not_found")
        evidence_ids = finding.get("evidence_ids") or []
        if status in {"contradicted", "partial"} and not evidence_ids:
            raise ValueError(f"{obligation_id}: contradicted or partial findings require evidence_ids")
        for evidence_id in evidence_ids:
            item = evidence_map.get(evidence_id)
            if not item or item["requirement_id"] != req_id:
                raise ValueError(f"{obligation_id}: invalid evidence reference {evidence_id}")


def _persist_spec_artifacts(workspace: Path, payload: Dict[str, Any]) -> None:
    if payload.get("artifact_type") != "rfc_corpus":
        return
    spec_dir = workspace / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    for key, filename in (
        ("clauses", "corpus.jsonl"),
        ("relations", "relations.jsonl"),
        ("dispositions", "dispositions.jsonl"),
        ("requirement_packs", "requirement-packs.jsonl"),
    ):
        rows = payload.get(key) or []
        (spec_dir / filename).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    _write_json(spec_dir / "scope.json", payload.get("scope") or {})
    _write_json(spec_dir / "coverage.json", payload.get("coverage") or {})


def _coverage_context(workspace: Path, repo: Path) -> Dict[str, Any]:
    db_path = workspace / "code-index" / "codefacts.sqlite"
    coverage: Dict[str, Any] = {
        "text_index": "available",
        "symbol_index": "unknown",
        "reference_index": "unknown",
        "call_index": "unknown",
        "tree_sitter": "unknown",
    }
    if not db_path.exists():
        coverage.update({"symbol_index": "unavailable", "reference_index": "unavailable", "call_index": "unavailable"})
        return coverage
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        tool = connection.execute("SELECT * FROM tool_runs WHERE tool='aider-tree-sitter'").fetchone()
        symbols = connection.execute("SELECT count(*) FROM symbols").fetchone()[0]
        refs = connection.execute("SELECT count(*) FROM refs").fetchone()[0]
        calls = connection.execute("SELECT count(*) FROM calls").fetchone()[0]
        if tool and tool["available"] and tool["executed"]:
            ratio = (tool["files_succeeded"] / tool["files_attempted"]) if tool["files_attempted"] else 0
            coverage["tree_sitter"] = "available" if ratio >= 0.8 else "partial"
        else:
            coverage["tree_sitter"] = "unavailable"
        coverage["symbol_index"] = "good" if symbols else "unavailable"
        coverage["reference_index"] = "partial" if refs else "unavailable"
        coverage["call_index"] = "heuristic" if calls else "unavailable"
    finally:
        connection.close()
    return coverage


def _code_hints_for_requirement(workspace: Path, requirement: Dict[str, Any], *, symbol_limit: int = 10, component_limit: int = 5) -> Dict[str, Any]:
    affinity = _pack_code_affinity(workspace, requirement, symbol_limit=symbol_limit, component_limit=component_limit)
    return {
        "components": affinity.get("components") or [],
        "symbols": affinity.get("symbols") or [],
        "files": affinity.get("files") or [],
        "symbol_families": affinity.get("symbol_families") or [],
        "source": affinity.get("source") or "sqlite_codefacts",
    }


def _pack_code_affinity(
    workspace: Path, requirement: Dict[str, Any], *, symbol_limit: int = 10,
    component_limit: int = 5, file_limit: int = 8,
) -> Dict[str, Any]:
    db_path = workspace / "code-index" / "codefacts.sqlite"
    if not db_path.exists():
        return {"components": [], "symbols": [], "files": [], "symbol_families": [], "source": "unavailable"}
    terms = _hint_terms(requirement)
    if not terms:
        return {"components": [], "symbols": [], "files": [], "symbol_families": [], "source": "sqlite_codefacts"}
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        symbol_scores: Counter[str] = Counter()
        component_scores: Counter[str] = Counter()
        file_scores: Counter[str] = Counter()
        family_scores: Counter[str] = Counter()
        for term in terms[:6]:
            pattern = f"%{term.lower()}%"
            for row in connection.execute(
                "SELECT s.name, f.path, f.component FROM symbols s JOIN files f USING(file_id) "
                "WHERE lower(s.name) LIKE ? LIMIT 30",
                (pattern,),
            ).fetchall():
                symbol_scores[row["name"]] += 1
                component_scores[row["component"]] += 1
                file_scores[row["path"]] += 1
                family = _symbol_family(row["name"])
                if family:
                    family_scores[family] += 1
            for row in connection.execute(
                "SELECT path, component FROM files WHERE lower(path) LIKE ? OR lower(component) LIKE ? LIMIT 30",
                (pattern, pattern),
            ).fetchall():
                component_scores[row["component"]] += 1
                file_scores[row["path"]] += 1
                for part in Path(row["path"]).parts:
                    family = _symbol_family(part)
                    if family:
                        family_scores[family] += 1
        _score_file_content_affinity(workspace, connection, terms, component_scores, file_scores, family_scores)
        components = _rank_components(component_scores, component_limit)
        families = _rank_symbol_families(family_scores, 8)
        return {
            "components": components,
            "symbols": [name for name, _score in symbol_scores.most_common(symbol_limit)],
            "files": [name for name, _score in file_scores.most_common(file_limit)],
            "symbol_families": families,
            "source": "sqlite_codefacts",
        }
    finally:
        connection.close()


def _score_file_content_affinity(
    workspace: Path, connection: sqlite3.Connection, terms: List[str],
    component_scores: Counter[str], file_scores: Counter[str], family_scores: Counter[str],
) -> None:
    repo = Path(_state(workspace)["repo"])
    useful_terms = [term for term in terms if len(term) >= 3][:24]
    if not useful_terms:
        return
    rows = connection.execute(
        "SELECT path, component, source_role, size FROM files WHERE language IS NOT NULL ORDER BY source_role='production' DESC, path LIMIT 500"
    ).fetchall()
    for row in rows:
        if int(row["size"]) > 2_000_000:
            continue
        try:
            text = (repo / row["path"]).read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        score = sum(1 for term in useful_terms if term in text)
        if not score:
            continue
        weight = score * (3 if row["source_role"] == "production" else 1)
        file_scores[row["path"]] += weight
        component_scores[row["component"]] += weight
        for part in Path(row["path"]).parts:
            family = _symbol_family(part)
            if family:
                family_scores[family] += score


def _symbol_family(name: str) -> str:
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+|_", name.lower()) if len(token) >= 3]
    if not tokens:
        compact = re.sub(r"[^A-Za-z0-9]+", "", name.lower())
        return compact[:12] if len(compact) >= 3 else ""
    return tokens[0][:16]


def _rank_components(scores: Counter[str], limit: int) -> List[str]:
    ranked = sorted(scores.items(), key=lambda item: (_component_rank_score(item[0], item[1]), item[0]), reverse=True)
    useful = [name for name, _score in ranked if not _is_low_value_component(name)]
    return useful[:limit]


def _component_rank_score(component: str, score: int) -> float:
    value = float(score)
    if _is_high_value_component(component):
        value += 20.0
    if _is_low_value_component(component):
        value -= 50.0
    return value


def _is_high_value_component(component: str) -> bool:
    return any(component == prefix or component.startswith(f"{prefix}/") for prefix in HIGH_VALUE_COMPONENT_PREFIXES)


def _is_low_value_component(component: str) -> bool:
    return any(re.search(pattern, component) for pattern in LOW_VALUE_COMPONENT_PATTERNS)


def _rank_symbol_families(scores: Counter[str], limit: int) -> List[str]:
    return [
        name for name, _score in scores.most_common()
        if name not in LOW_VALUE_SYMBOL_FAMILIES
    ][:limit]


def _hint_terms(requirement: Dict[str, Any]) -> List[str]:
    raw_text = " ".join(
        str(requirement.get(field) or "")
        for field in ("document", "section", "quote", "normalized", "capability")
    )
    raw_keywords = [str(term) for term in (requirement.get("keywords") or [])]
    text = " ".join([raw_text, *raw_keywords])
    terms: List[str] = []
    for acronym in _phrase_acronyms(text):
        _append_hint_term(terms, acronym)
        if "ipv6" in text.lower() or "icmpv6" in text.lower():
            _append_hint_term(terms, f"{acronym}6")
    for term in raw_keywords:
        _append_hint_term(terms, term)
        for part in re.split(r"[^A-Za-z0-9]+|_", term):
            _append_hint_term(terms, part)
    for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text):
        _append_hint_term(terms, term)
        for part in re.split(r"[^A-Za-z0-9]+|_", term):
            _append_hint_term(terms, part)
    stop = {"rfc", "must", "should", "shall", "not", "for", "the", "and", "all", "section"}
    return [term for term in terms if term not in stop][:40]


def _append_hint_term(terms: List[str], term: str) -> None:
    value = re.sub(r"[^A-Za-z0-9_]+", "", str(term).lower())
    if len(value) >= 2 and value not in terms:
        terms.append(value)
    if "ipv6" in value and "ip6" not in terms:
        terms.append("ip6")
    if value.endswith("v6"):
        v6_alias = value[:-2] + "6"
        if len(v6_alias) >= 2 and v6_alias not in terms:
            terms.append(v6_alias)
    aliases = {
        "fragment": "frag",
        "fragments": "frag",
        "fragmentation": "frag",
        "extension": "ext",
        "advertisement": "adv",
        "advertisements": "adv",
    }
    alias = aliases.get(value)
    if alias and alias not in terms:
        terms.append(alias)
    if value.startswith("rfc") and value[3:].isdigit() and value[3:] not in terms:
        terms.append(value[3:])


def _phrase_acronyms(text: str) -> List[str]:
    acronyms: List[str] = []
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,4})\b", text):
        words = match.group(1).split()
        initials = "".join(word[0].lower() for word in words if word and word[0].isalpha())
        if 2 <= len(initials) <= 5 and initials not in acronyms:
            acronyms.append(initials)
    return acronyms


def _pack_coverage(workspace: Path, records: List[Dict[str, Any]], verifications: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    spec_coverage = _load_json(workspace / "spec" / "coverage.json") if (workspace / "spec" / "coverage.json").exists() else {}
    statuses = Counter(record["status"] for record in records)
    review_counts = Counter(item["verdict"] for item in verifications.values())
    return {
        "corpus": spec_coverage,
        "packs": {
            "total": len(records),
            "investigated": sum(1 for record in records if record.get("investigation")),
            "pending": 0,
        },
        "investigations": dict(sorted(statuses.items())),
        "reviews": dict(sorted(review_counts.items())),
    }


def _validate_verification_check(check: Any) -> None:
    if not isinstance(check, dict):
        raise ValueError("verification check must be an object")
    if check.get("check") not in {
        "source_location", "requirement_alignment", "production_relevance", "search_scope",
        "tool_capability", "alternate_implementation", "build_inclusion",
        "conditional_compilation", "bypass_path",
    }:
        raise ValueError("invalid verification check type")
    if check.get("outcome") not in {"passed", "failed", "inconclusive"}:
        raise ValueError("invalid verification check outcome")
    if not isinstance(check.get("note", ""), str):
        raise ValueError("verification check note must be a string")
    if not isinstance(check.get("evidence_ids", []), list):
        raise ValueError("verification check evidence_ids must be an array")


def _next_batch_action_locked(workspace: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    _finalize_active_batch(workspace, state)
    batches = _load_json(workspace / "batches.json")["batches"]
    cursor = int(state.get("batch_cursor") or 0)
    if cursor < len(batches):
        batch = batches[cursor]
        state["batch_cursor"] = cursor + 1
        state["active_batch_id"] = batch["batch_id"]
        return {"next_action": "investigate_batch", "batch": _batch_packet(workspace, batch), "batch_id": batch["batch_id"]}
    _refresh_stage(state)
    if state["assembly_allowed"]:
        return {"next_action": "finish" if state["stage"] != "assembled" else "done"}
    return {"next_action": "blocked", "reason": "batch audit state has no runnable transition", "status": audit_status(workspace)}


def _finalize_active_batch(workspace: Path, state: Dict[str, Any]) -> None:
    batch_id = state.get("active_batch_id")
    if not batch_id:
        return
    batch = _batch_by_id(workspace, batch_id)
    for req_id in batch["requirement_ids"]:
        if state["requirements"][req_id]["investigation"] != "submitted":
            _persist_pack_result(
                workspace, state,
                {
                    "requirement_id": req_id, "status": "unknown",
                    "summary": "batch_agent_failed_or_result_missing",
                    "evidence_ids": [], "spec_clause_ids": [], "confidence": 0.0,
                },
                reason="batch_agent_failed_or_result_missing",
            )
    state["active_batch_id"] = None
    _refresh_stage(state)


def _build_audit_batches(workspace: Path, requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    affinities = {req["id"]: _pack_code_affinity(workspace, req) for req in requirements}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for req in requirements:
        grouped.setdefault(_initial_topic_key(req, affinities[req["id"]]), []).append(req)
    topics = [_make_topic(key, rows, affinities) for key, rows in grouped.items()]
    topics = _merge_topics_to_budget(topics, TARGET_BATCHES, min_score=MIN_TOPIC_MERGE_SCORE)
    if len(topics) > HARD_MAX_BATCHES:
        topics = _merge_topics_to_budget(topics, HARD_MAX_BATCHES, min_score=MIN_TOPIC_MERGE_SCORE)
    topics = _split_oversized_topics(topics, affinities)
    topics = sorted(topics, key=lambda item: (-len(item["requirements"]), item["key"]))
    return [_make_batch(index, topic) for index, topic in enumerate(topics, 1)]


def _initial_topic_key(req: Dict[str, Any], affinity: Dict[str, Any]) -> str:
    document = _document_group(req)
    component = (affinity.get("components") or ["unknown"])[0]
    family = (affinity.get("symbol_families") or ["general"])[0]
    if component == "unknown":
        return f"{document}|{family}"
    return f"{document}|{component}|{family}"


def _document_group(req: Dict[str, Any]) -> str:
    document = str(req.get("document") or "DOC")
    match = re.search(r"\bRFC\s*([0-9]{3,5})\b", document, re.I)
    if match:
        return f"RFC{match.group(1)}"
    return re.sub(r"[^A-Za-z0-9]+", "", document).upper()[:24] or "DOC"


def _make_topic(key: str, rows: List[Dict[str, Any]], affinities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    topic = {
        "key": key,
        "requirements": sorted(rows, key=_requirement_sort_key),
        "components": Counter(),
        "symbols": Counter(),
        "files": Counter(),
        "symbol_families": Counter(),
        "keywords": Counter(),
        "documents": Counter(),
    }
    for req in rows:
        affinity = affinities[req["id"]]
        for field in ("components", "symbols", "files", "symbol_families"):
            for value in affinity.get(field) or []:
                topic[field][value] += 1
        for value in _hint_terms(req)[:12]:
            topic["keywords"][value] += 1
        topic["documents"][str(req.get("document") or "")] += 1
    return topic


def _merge_topics_to_budget(topics: List[Dict[str, Any]], target: int, *, min_score: float = 0.0) -> List[Dict[str, Any]]:
    topics = list(topics)
    while len(topics) > target:
        best_pair = None
        best_score = None
        for left_index in range(len(topics)):
            for right_index in range(left_index + 1, len(topics)):
                score = _topic_merge_score(topics[left_index], topics[right_index])
                pair_key = (score, -left_index, -right_index)
                if best_score is None or pair_key > best_score:
                    best_score = pair_key
                    best_pair = (left_index, right_index)
        if best_pair is None or best_score is None or best_score[0] < min_score:
            break
        left_index, right_index = best_pair
        merged = _merge_two_topics(topics[left_index], topics[right_index])
        topics = [topic for index, topic in enumerate(topics) if index not in best_pair]
        topics.append(merged)
    return topics


def _split_oversized_topics(topics: List[Dict[str, Any]], affinities: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for topic in topics:
        chunk: List[Dict[str, Any]] = []
        clause_count = 0
        part = 1
        for req in topic["requirements"]:
            req_clause_count = len(req.get("clause_ids") or []) or 1
            if chunk and (
                len(chunk) >= MAX_BATCH_PACKET_PACKS
                or clause_count + req_clause_count > MAX_BATCH_PACKET_CLAUSES
            ):
                result.append(_make_topic(_chunk_topic_key(chunk, affinities, part), chunk, affinities))
                part += 1
                chunk = []
                clause_count = 0
            chunk.append(req)
            clause_count += req_clause_count
        if chunk:
            result.append(_make_topic(_chunk_topic_key(chunk, affinities, part if part > 1 else 0), chunk, affinities))
    return result


def _chunk_topic_key(rows: List[Dict[str, Any]], affinities: Dict[str, Dict[str, Any]], part: int) -> str:
    documents = Counter(_document_group(req) for req in rows)
    components: Counter[str] = Counter()
    families: Counter[str] = Counter()
    for req in rows:
        affinity = affinities[req["id"]]
        for value in affinity.get("components") or []:
            components[value] += 1
        for value in affinity.get("symbol_families") or []:
            families[value] += 1
    document = documents.most_common(1)[0][0] if documents else "DOC"
    component = components.most_common(1)[0][0] if components else "unknown"
    family = families.most_common(1)[0][0] if families else "general"
    suffix = f"#{part}" if part else ""
    return f"{document}|{component}|{family}{suffix}"


def _topic_merge_score(left: Dict[str, Any], right: Dict[str, Any]) -> float:
    score = 0.0
    left_component = next(iter(left["components"]), None)
    right_component = next(iter(right["components"]), None)
    if left_component and left_component != "unknown" and left_component == right_component:
        score += 20
    component_overlap = (set(left["components"]) & set(right["components"])) - {"unknown"}
    family_overlap = (set(left["symbol_families"]) & set(right["symbol_families"])) - {"general", "unknown"}
    score += 8 * len(component_overlap)
    score += 6 * len(family_overlap)
    score += 4 * len(set(left["files"]) & set(right["files"]))
    score += 1.5 * len(set(left["documents"]) & set(right["documents"]))
    score += 1 * len(set(left["keywords"]) & set(right["keywords"]))
    return score


def _merge_two_topics(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    merged = {
        "key": f"{left['key']}+{right['key']}",
        "requirements": sorted(left["requirements"] + right["requirements"], key=_requirement_sort_key),
        "components": Counter(left["components"]),
        "symbols": Counter(left["symbols"]),
        "files": Counter(left["files"]),
        "symbol_families": Counter(left["symbol_families"]),
        "keywords": Counter(left["keywords"]),
        "documents": Counter(left["documents"]),
    }
    for field in ("components", "symbols", "files", "symbol_families", "keywords", "documents"):
        merged[field].update(right[field])
    return merged


def _make_batch(index: int, topic: Dict[str, Any]) -> Dict[str, Any]:
    rows = topic["requirements"]
    hints = {
        "components": [item for item, _count in topic["components"].most_common(8)],
        "symbols": [item for item, _count in topic["symbols"].most_common(16)],
        "files": [item for item, _count in topic["files"].most_common(16)],
        "symbol_families": [item for item, _count in topic["symbol_families"].most_common(8)],
        "source": "sqlite_codefacts_affinity",
    }
    return {
        "batch_id": f"BATCH-{index:04d}",
        "topic": f"BATCH-{topic['key'].replace('|', '-')[:80]}-{index:04d}",
        "group_key": topic["key"],
        "requirement_ids": [req["id"] for req in rows],
        "requirements": rows,
        "code_hints": hints,
        "limits": {"max_queries": MAX_BATCH_QUERIES, "max_text_queries": MAX_BATCH_TEXT_QUERIES},
    }


def _batch_packet(workspace: Path, batch: Dict[str, Any]) -> Dict[str, Any]:
    packet = dict(batch)
    packet["requirements"] = [_compact_requirement(req) for req in batch["requirements"]]
    packet["discovery_plan"] = _batch_discovery_plan(workspace, batch)
    packet["investigation_rules"] = {
        "text_search_is_candidate_discovery_only": True,
        "final_covered_or_partial_requires_source_evidence": True,
        "source_evidence_precision": "exact_source_span",
        "covered_requires_counterexample_search": True,
        "use_discovery_plan_first": True,
        "max_initial_text_searches_before_source": 2,
        "negative_patterns": [
            "not implemented", "TODO", "XXX",
            "max", "limit", "cap", "hard-coded",
            "only", "immediate", "direct header",
            "absent", "missing", "no entry point",
            "enqueue", "filter", "bypass", "divert",
        ],
    }
    return packet


def _batch_discovery_plan(workspace: Path, batch: Dict[str, Any]) -> Dict[str, Any]:
    hints = batch.get("code_hints") or {}
    symbols = list(dict.fromkeys(hints.get("symbols") or []))[:MAX_DISCOVERY_SYMBOLS]
    files = list(dict.fromkeys(hints.get("files") or []))[:MAX_DISCOVERY_FILES]
    components = list(dict.fromkeys(hints.get("components") or []))[:5]
    plan: Dict[str, Any] = {
        "source": "sqlite_codefacts",
        "preferred_order": ["source_windows", "symbol_queries", "reference_queries", "component_queries", "text_fallback"],
        "source_windows": [],
        "symbol_queries": [{"operation": "symbol", "term": symbol} for symbol in symbols],
        "reference_queries": [{"operation": "references", "term": symbol} for symbol in symbols[:8]],
        "component_queries": [{"operation": "component", "term": component} for component in components],
        "text_fallback_terms": _batch_fallback_terms(batch)[:8],
    }
    db_path = workspace / "code-index" / "codefacts.sqlite"
    if not db_path.exists():
        plan["source"] = "unavailable"
        return plan
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        windows: List[Dict[str, Any]] = []
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            rows = connection.execute(
                "SELECT s.name, s.kind, s.start_line, s.end_line, f.path, f.line_count, f.source_role, f.component "
                "FROM symbols s JOIN files f USING(file_id) "
                f"WHERE s.name IN ({placeholders}) "
                "ORDER BY f.source_role='production' DESC, s.start_line LIMIT ?",
                (*symbols, MAX_DISCOVERY_SOURCE_WINDOWS * 2),
            ).fetchall()
            for row in rows:
                windows.append(_discovery_source_window(
                    row["path"], row["line_count"], int(row["start_line"]), int(row["end_line"]),
                    reason=f"symbol:{row['name']}",
                ))
        if len(windows) < MAX_DISCOVERY_SOURCE_WINDOWS and files:
            placeholders = ",".join("?" for _ in files)
            rows = connection.execute(
                "SELECT path, line_count, source_role, component FROM files "
                f"WHERE path IN ({placeholders}) "
                "ORDER BY source_role='production' DESC, path LIMIT ?",
                (*files, MAX_DISCOVERY_FILES),
            ).fetchall()
            for row in rows:
                windows.append(_discovery_source_window(row["path"], row["line_count"], 1, min(80, int(row["line_count"])), reason="top_file"))
        plan["source_windows"] = _unique_source_windows(windows)[:MAX_DISCOVERY_SOURCE_WINDOWS]
    finally:
        connection.close()
    return plan


def _discovery_source_window(path: str, line_count: int, start_line: int, end_line: int, *, reason: str) -> Dict[str, Any]:
    total_lines = max(1, int(line_count))
    start = max(1, start_line - 8)
    end = min(total_lines, max(end_line + 20, start + 40))
    return {"operation": "source", "path": path, "start_line": start, "end_line": end, "reason": reason}


def _unique_source_windows(windows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for window in windows:
        key = (window["path"], window["start_line"], window["end_line"])
        if key in seen:
            continue
        seen.add(key)
        result.append(window)
    return result


def _batch_fallback_terms(batch: Dict[str, Any]) -> List[str]:
    terms: List[str] = []
    for req in batch.get("requirements") or []:
        for term in _hint_terms(req):
            if term not in terms:
                terms.append(term)
    return terms


def _compact_requirement(req: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: req.get(key)
        for key in ("id", "document", "section", "quote", "clause_ids", "normative_strength")
        if key in req
    }


def _requirement_sort_key(req: Dict[str, Any]) -> tuple[str, List[int], str]:
    section_numbers = [int(item) for item in re.findall(r"\d+", str(req.get("section") or ""))]
    return (str(req.get("document") or ""), section_numbers, req["id"])


def _batch_by_id(workspace: Path, batch_id: str) -> Dict[str, Any]:
    batch = next((item for item in _load_json(workspace / "batches.json")["batches"] if item["batch_id"] == batch_id), None)
    if not batch:
        raise ValueError(f"unknown batch id: {batch_id}")
    return batch


def _requirement_in_active_batch(workspace: Path, state: Dict[str, Any], req_id: str) -> bool:
    batch_id = state.get("active_batch_id")
    if not batch_id:
        return False
    return req_id in set(_batch_by_id(workspace, batch_id)["requirement_ids"])


def _validate_batch_results(workspace: Path, batch: Dict[str, Any], rows: Any) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not isinstance(rows, list):
        raise ValueError("batch results must be an array")
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    seen = set()
    for index, row in enumerate(rows):
        try:
            result = _validate_one_batch_result(workspace, batch, row, index, seen)
            accepted.append(result)
            seen.add(result["requirement_id"])
        except ValueError as exc:
            rejected.append({
                "index": index,
                "requirement_id": row.get("requirement_id") or row.get("requirementId") if isinstance(row, dict) else None,
                "reason": str(exc),
            })
    return accepted, rejected


def _validate_one_batch_result(
    workspace: Path, batch: Dict[str, Any], row: Any, index: int, seen: set[str],
) -> Dict[str, Any]:
    allowed = set(batch["requirement_ids"])
    requirements = {item["id"]: item for item in batch["requirements"]}
    evidence = _jsonl_map(workspace / "evidence.jsonl", "evidence_id")
    if not isinstance(row, dict):
        raise ValueError(f"results[{index}] must be an object")
    req_id = str(row.get("requirement_id") or row.get("requirementId") or "")
    if req_id not in allowed:
        raise ValueError(f"results[{index}] requirement_id is not in current batch: {req_id}")
    if req_id in seen:
        raise ValueError(f"duplicate batch result for {req_id}")
    status = str(row.get("status") or "")
    if status not in {"covered", "partial", "violated", "unknown"}:
        raise ValueError("batch result status must be covered, partial, violated, or unknown")
    summary = str(row.get("summary") or "").strip()
    if not summary:
        raise ValueError(f"{req_id}: summary is required")
    evidence_ids = row.get("evidence_ids") if "evidence_ids" in row else row.get("evidenceIds")
    evidence_ids = evidence_ids or []
    if not isinstance(evidence_ids, list):
        raise ValueError(f"{req_id}: evidence_ids must be an array")
    for evidence_id in evidence_ids:
        item = evidence.get(evidence_id)
        if not item or not _evidence_allowed_for_batch_result(item, batch["batch_id"], req_id):
            raise ValueError(f"{req_id}: invalid evidence_id {evidence_id}")
    if status in {"covered", "partial"} and not _has_source_span_evidence(evidence, evidence_ids):
        raise ValueError(f"{req_id}: {status} result requires exact source evidence; text/symbol hits are discovery only")
    if status == "violated" and evidence_ids and not _has_source_span_evidence(evidence, evidence_ids):
        raise ValueError(f"{req_id}: violated result with code evidence requires exact source evidence")
    spec_clause_ids = row.get("spec_clause_ids") if "spec_clause_ids" in row else row.get("specClauseIds")
    spec_clause_ids = spec_clause_ids or []
    allowed_clauses = set(requirements[req_id].get("clause_ids") or [req_id])
    if not isinstance(spec_clause_ids, list) or not set(spec_clause_ids).issubset(allowed_clauses):
        raise ValueError(f"{req_id}: spec_clause_ids must belong to the Pack")
    issue = row.get("issue")
    if status in {"partial", "violated"}:
        _validate_batch_issue(issue)
    confidence = row.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError(f"{req_id}: confidence must be between 0 and 1")
    return {
        "requirement_id": req_id, "status": status, "summary": summary,
        "spec_clause_ids": spec_clause_ids, "evidence_ids": evidence_ids,
        "confidence": confidence, "issue": issue,
    }


def _evidence_allowed_for_batch_result(evidence: Dict[str, Any], batch_id: str, req_id: str) -> bool:
    return evidence.get("batch_id") == batch_id or evidence.get("requirement_id") == req_id


def _has_source_span_evidence(evidence: Dict[str, Dict[str, Any]], evidence_ids: List[str]) -> bool:
    for evidence_id in evidence_ids:
        item = evidence.get(evidence_id) or {}
        if item.get("backend") == "source_read" and item.get("precision") == "exact_source_span":
            return True
    return False


def _validate_batch_issue(issue: Any) -> None:
    if not isinstance(issue, dict):
        raise ValueError("partial or violated batch result requires issue")
    title = str(issue.get("title") or "").strip()
    if not title:
        raise ValueError("issue title is required")
    severity = issue.get("severity") or "medium"
    if severity not in {"critical", "high", "medium", "low"}:
        raise ValueError("invalid issue severity")


def _persist_pack_result(workspace: Path, state: Dict[str, Any], result: Dict[str, Any], *, reason: str) -> None:
    req_id = result["requirement_id"]
    if state["requirements"][req_id]["investigation"] == "submitted":
        return
    status = result["status"]
    proposed_status = {"covered": "covered", "partial": "partial", "violated": "violated", "unknown": "unknown"}[status]
    issue = None
    if status in {"partial", "violated"}:
        raw_issue = result.get("issue") or {}
        issue = {
            "title": raw_issue.get("title") or "Spec-code mismatch",
            "description": result["summary"],
            "match_type": raw_issue.get("match_type") or "mismatch",
            "severity": raw_issue.get("severity") or "medium",
            "confidence": result.get("confidence", 0.5),
        }
        _validate_issue(issue)
    canonical = {
        "requirement_id": req_id, "proposed_status": proposed_status, "reasoning": result["summary"],
        "query_ids": sorted(
            item["query_id"] for item in _jsonl_map(workspace / "queries.jsonl", "query_id").values()
            if item["role"] == "investigator"
            and (
                item["requirement_id"] == req_id
                or (state.get("active_batch_id") and item.get("batch_id") == state.get("active_batch_id"))
            )
        ),
        "evidence_ids": result.get("evidence_ids") or [], "counterexample_query_ids": [],
        "claim_scope": "batch_result", "unresolved_questions": [] if status != "unknown" else [reason],
        "issue": issue, "agent_conclusion": status, "negative_checks": [],
        "obligations": [], "obligation_results": [], "findings": [],
        "spec_clause_ids": result.get("spec_clause_ids") or [],
        "confidence": result.get("confidence", 0.5), "submitted_at": _now(),
    }
    _transition(state, req_id, "investigation_failed" if status == "unknown" else "batch_result_submitted")
    _upsert(workspace / "investigations.json", "investigations", req_id, canonical)


def _next_action_locked(workspace: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    applied = _apply_terminal_fallbacks(workspace, state)
    outstanding = _outstanding_dispatched_action(workspace)
    if outstanding:
        return {
            "next_action": "awaiting_dispatch_result",
            "action": outstanding,
            "action_id": outstanding["action_id"],
            "requirement_id": outstanding["requirement_id"],
            "instruction": "Call audit_dispatch_result for the outstanding action before dispatching more work.",
            "applied_fallbacks": applied,
        }
    requirements = {item["id"]: item for item in _load_json(workspace / "requirements.json")["requirements"]}
    for req_id, item in state["requirements"].items():
        if item["investigation"] == "pending":
            requirement = requirements[req_id]
            action = _ensure_action(workspace, state, req_id, "frame_obligations", expected_before="pending", expected_after="framed")
            return {
                "next_action": "frame_obligations", "action": action, "action_id": action["action_id"],
                "requirement_id": req_id, "requirement_pack": requirement, "requirement": requirement,
                "code_hints": _code_hints_for_requirement(workspace, requirement),
                "instruction": "Frame 1 to 3 implementation obligations tied to current pack clauses.",
            }
        if item["investigation"] == "framed":
            requirement = requirements[req_id]
            obligations = _draft_for_requirement(workspace, req_id)["obligations"]
            action = _ensure_action(workspace, state, req_id, "investigate", expected_before="framed", expected_after="submitted")
            return {
                "next_action": "investigate", "action": action, "action_id": action["action_id"],
                "requirement_id": req_id, "requirement_pack": requirement, "requirement": requirement,
                "obligations": obligations, "code_hints": _code_hints_for_requirement(workspace, requirement),
                "required_checks": required_checks(requirement, obligations),
                "instruction": "Investigate the framed obligations and submit one conclusion.",
            }
    for req_id, item in state["requirements"].items():
        if item["verification"] == "pending" and item["investigation"] == "submitted":
            action = _ensure_action(workspace, state, req_id, "review", expected_before="pending", expected_after="submitted")
            return {"next_action": "review", "action": action, "action_id": action["action_id"], "requirement_id": req_id, "review_packet": review_bundle(workspace, req_id)}
    if state["assembly_allowed"]:
        return {"next_action": "finish" if state["stage"] != "assembled" else "done"}
    return {"next_action": "blocked", "reason": "audit state has no runnable transition", "status": audit_status(workspace)}


def _actions_path(workspace: Path) -> Path:
    return workspace / "actions.json"


def _load_actions(workspace: Path) -> Dict[str, Any]:
    path = _actions_path(workspace)
    if not path.exists():
        return {"schema_version": "1.0", "actions": []}
    return _load_json(path)


def _ensure_action(
    workspace: Path, state: Dict[str, Any], req_id: str, action_type: str,
    *, expected_before: str, expected_after: str,
) -> Dict[str, Any]:
    payload = _load_actions(workspace)
    for action in reversed(payload["actions"]):
        if (
            action.get("requirement_id") == req_id
            and action.get("action_type") == action_type
            and action.get("status") == "dispatched"
        ):
            return action
    attempts = [
        int(action.get("attempt", 0)) for action in payload["actions"]
        if action.get("requirement_id") == req_id and action.get("action_type") == action_type
    ]
    attempt = (max(attempts) if attempts else 0) + 1
    state.setdefault("counters", {})["action"] = int(state.setdefault("counters", {}).get("action", 0)) + 1
    now = _now()
    action = {
        "action_id": f"A-{state['counters']['action']:07d}",
        "action_type": action_type,
        "requirement_id": req_id,
        "attempt": attempt,
        "max_attempts": MAX_SUBAGENT_ATTEMPTS,
        "expected_before": expected_before,
        "expected_after": expected_after,
        "status": "dispatched",
        "error": "",
        "created_at": now,
        "dispatched_at": now,
    }
    payload["actions"].append(action)
    _write_json(_actions_path(workspace), payload)
    return action


def _current_action(workspace: Path, req_id: str, action_type: str, action_id: str = "") -> Optional[Dict[str, Any]]:
    actions = _load_actions(workspace)["actions"]
    if action_id:
        action = next((item for item in actions if item.get("action_id") == action_id), None)
        if not action or action.get("requirement_id") != req_id or action.get("action_type") != action_type:
            return None
        return action
    for action in reversed(actions):
        if action.get("requirement_id") == req_id and action.get("action_type") == action_type and action.get("status") == "dispatched":
            return action
    return None


def _outstanding_dispatched_action(workspace: Path) -> Optional[Dict[str, Any]]:
    for action in _load_actions(workspace)["actions"]:
        if action.get("status") == "dispatched":
            return action
    return None


def _apply_terminal_fallbacks(workspace: Path, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = _load_actions(workspace)
    applied = []
    changed = False
    for action in payload["actions"]:
        if action.get("status") != "failed_terminal" or action.get("fallback_applied_at"):
            continue
        recovery = _finalize_failed_dispatch(
            workspace, state, action["requirement_id"], action["action_type"],
            _actual_state_for_action(state, action["requirement_id"], action["action_type"]),
        )
        action["fallback_applied_at"] = _now()
        action["fallback"] = recovery
        applied.append({"action_id": action["action_id"], **recovery})
        changed = True
    if changed:
        _write_json(_actions_path(workspace), payload)
    return applied


def _update_action(workspace: Path, action_id: str, *, status: str, error: str = "") -> Dict[str, Any]:
    if status not in {"created", "dispatched", "committed", "failed", "failed_terminal"}:
        raise ValueError(f"invalid action status: {status}")
    payload = _load_actions(workspace)
    for action in payload["actions"]:
        if action.get("action_id") == action_id:
            action["status"] = status
            action["error"] = error
            if status == "committed":
                action["committed_at"] = _now()
            if status in {"failed", "failed_terminal"}:
                action["failed_at"] = _now()
            _write_json(_actions_path(workspace), payload)
            return action
    raise ValueError(f"unknown action_id: {action_id}")


def _dispatch_states(state: Dict[str, Any], req_id: str, action: str) -> tuple[str, str]:
    item = state["requirements"][req_id]
    if action == "frame_obligations":
        return "framed", item["investigation"]
    if action == "investigate":
        return "submitted", item["investigation"]
    return "submitted", item["verification"]


def _actual_state_for_action(state: Dict[str, Any], req_id: str, action: str) -> str:
    return _dispatch_states(state, req_id, action)[1]


def _transition(state: Dict[str, Any], req_id: str, event: str, *, verification: Optional[str] = None) -> None:
    item = state["requirements"][req_id]
    if event == "obligations_framed":
        if item["investigation"] != "pending":
            raise ValueError(f"invalid transition {event} from investigation={item['investigation']}")
        item["investigation"] = "framed"
    elif event == "investigation_submitted":
        if item["investigation"] != "framed":
            raise ValueError(f"invalid transition {event} from investigation={item['investigation']}")
        if verification not in {"pending", "not_required"}:
            raise ValueError("investigation_submitted requires verification pending or not_required")
        item["investigation"] = "submitted"
        item["verification"] = verification
    elif event == "investigation_failed":
        if item["investigation"] not in {"pending", "framed"}:
            raise ValueError(f"invalid transition {event} from investigation={item['investigation']}")
        item["investigation"] = "submitted"
        item["verification"] = "not_required"
    elif event == "batch_result_submitted":
        if item["investigation"] not in {"pending", "framed"}:
            raise ValueError(f"invalid transition {event} from investigation={item['investigation']}")
        item["investigation"] = "submitted"
        item["verification"] = "not_required"
    elif event in {"review_submitted", "review_failed"}:
        if item["investigation"] != "submitted" or item["verification"] != "pending":
            raise ValueError(f"invalid transition {event} from investigation={item['investigation']} verification={item['verification']}")
        item["verification"] = "submitted"
    else:
        raise ValueError(f"unknown transition event: {event}")
    _refresh_stage(state)


def _finalize_failed_dispatch(workspace: Path, state: Dict[str, Any], req_id: str, action: str, previous_state: str) -> Dict[str, Any]:
    if action in {"frame_obligations", "investigate"}:
        reason = "framing_agent_failed_to_submit" if action == "frame_obligations" else "investigator_failed_to_submit"
        canonical = {
            "requirement_id": req_id,
            "proposed_status": "unknown",
            "reasoning": reason,
            "query_ids": sorted(
                item["query_id"] for item in _jsonl_map(workspace / "queries.jsonl", "query_id").values()
                if item["requirement_id"] == req_id and item["role"] == "investigator"
            ),
            "evidence_ids": [],
            "counterexample_query_ids": [],
            "claim_scope": "agent_failure",
            "unresolved_questions": [reason],
            "issue": None,
            "agent_conclusion": "uncertain",
            "negative_checks": [],
            "obligations": _draft_for_requirement(workspace, req_id).get("obligations", []) if previous_state == "framed" else [],
            "obligation_results": [],
            "findings": [],
            "submitted_at": _now(),
            "agent_failed": True,
            "failure_action": action,
        }
        _transition(state, req_id, "investigation_failed")
        _upsert(workspace / "investigations.json", "investigations", req_id, canonical)
        return {"finalized": "unknown_investigation", "current_state": "submitted", "reason": reason}
    canonical = {
        "requirement_id": req_id,
        "verdict": "needs_more_work",
        "reasoning": "reviewer_failed_to_submit",
        "query_ids": [],
        "evidence_ids": [],
        "challenges": ["reviewer_failed_to_submit"],
        "recommended_status": "unknown",
        "lightweight_review": True,
        "submitted_at": _now(),
        "agent_failed": True,
        "failure_action": action,
    }
    _transition(state, req_id, "review_failed")
    _upsert(workspace / "verifications.json", "verifications", req_id, canonical)
    return {"finalized": "failed_review", "current_state": "submitted", "reason": "reviewer_failed_to_submit"}


def _refresh_stage(state: Dict[str, Any]) -> None:
    values = list(state["requirements"].values())
    investigations_done = all(item["investigation"] == "submitted" for item in values)
    verifications_done = all(item["verification"] in {"submitted", "not_required"} for item in values)
    state["assembly_allowed"] = investigations_done and verifications_done
    state["stage"] = "ready_to_assemble" if state["assembly_allowed"] else ("verifying" if investigations_done else "investigating")


def _verification_required(workspace: Path, investigation: Dict[str, Any]) -> bool:
    status = investigation["proposed_status"]
    if status in {"violated", "partial", "no_evidence_found"}:
        return True
    if status in {"unknown", "out_of_scope", "non_verifiable"}:
        return False
    if investigation.get("claim_scope") != "local_fact":
        return True
    evidence = _jsonl_map(workspace / "evidence.jsonl", "evidence_id")
    precisions = {
        evidence[item].get("precision") for item in investigation.get("evidence_ids", []) if item in evidence
    }
    return not precisions or not precisions.issubset({"exact_source", "exact_source_span", "compiler_precise"})


def _assemble_issue(index: int, req: Dict[str, Any], investigation: Dict[str, Any], verification: Dict[str, Any], evidence_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    draft = investigation.get("issue") or {}
    evidence_ids = investigation["evidence_ids"]
    spec_evidence = _spec_evidence_for_issue(req, investigation)
    legacy_spec = spec_evidence[0] if spec_evidence else {"document": req.get("document"), "section": req.get("section"), "quote": req["quote"]}
    return {
        "id": f"ISSUE-{index:03d}", "requirement_id": req["id"],
        "title": draft.get("title") or req["normalized"], "match_type": draft.get("match_type") or investigation["proposed_status"],
        "severity": draft.get("severity") or "medium", "confidence": draft.get("confidence") or 0.6,
        "description": draft.get("description") or investigation["reasoning"],
        "spec_evidence": legacy_spec, "spec_evidence_items": spec_evidence,
        "evidence_ids": evidence_ids, "code_evidence": [evidence_map[item] for item in evidence_ids if item in evidence_map],
        "verification": {"verdict": verification["verdict"], "reasoning": verification["reasoning"], "challenges": verification["challenges"]},
    }


def _upsert(path: Path, key: str, req_id: str, value: Dict[str, Any]) -> None:
    payload = _load_json(path)
    rows = [item for item in payload[key] if item.get("requirement_id") != req_id]
    rows.append(value)
    payload[key] = sorted(rows, key=lambda item: item["requirement_id"])
    _write_json(path, payload)


def _state(workspace: Path) -> Dict[str, Any]:
    state = _load_json(workspace / "audit-state.json")
    requirements_path = workspace / "requirements.json"
    if requirements_path.exists() and _sha256_json(_load_json(requirements_path)) != state.get("requirements_sha256"):
        raise ValueError("locked requirements.json was modified after audit initialization")
    return state
def _save_state(workspace: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = _now(); _write_json(workspace / "audit-state.json", state)
def _require_requirement(state: Dict[str, Any], req_id: str) -> None:
    if req_id not in state["requirements"]: raise ValueError(f"unknown requirement id: {req_id}")
def _load_json(path: Path) -> Dict[str, Any]: return json.loads(path.read_text(encoding="utf-8"))
def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp"); temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); temp.replace(path)


def _write_sarif(path: Path, payload: Dict[str, Any]) -> None:
    results = []
    for issue in payload.get("issues", []):
        evidence = issue.get("code_evidence") or []
        locations = [_sarif_location(item) for item in evidence if item.get("path") and item.get("line")]
        result = {
            "ruleId": issue.get("match_type", "spec-code-consistency"),
            "level": {"critical": "error", "high": "error", "medium": "warning", "low": "note"}.get(str(issue.get("severity", "medium")).lower(), "warning"),
            "message": {"text": issue.get("description") or issue.get("title") or "Specification/code inconsistency"},
            "properties": {
                "issue_id": issue.get("id"), "requirement_id": issue.get("requirement_id"),
                "confidence": issue.get("confidence"), "evidence_ids": issue.get("evidence_ids") or [],
            },
        }
        if locations:
            result["locations"] = locations[:1]
            if len(locations) > 1:
                result["relatedLocations"] = [
                    {"id": index, **location} for index, location in enumerate(locations[1:], 1)
                ]
        results.append(result)
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "SpecDiff", "informationUri": "https://opencode.ai/", "rules": []}},
            "invocations": [{"executionSuccessful": True, "properties": {"audit_id": payload.get("audit_id")}}],
            "results": results,
        }],
    }
    _write_json(path, sarif)


def _sarif_location(evidence: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": evidence["path"]},
            "region": {"startLine": int(evidence["line"])},
        },
        "message": {"text": evidence.get("quote") or evidence.get("backend") or "Code evidence"},
    }
def _jsonl_map(path: Path, key: str) -> Dict[str, Dict[str, Any]]: return {item[key]: item for item in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}
def _sha256_json(payload: Dict[str, Any]) -> str: return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
def _audit_id(repo: Path, requirements: List[Dict[str, Any]]) -> str: return "AUDIT-" + hashlib.sha256((str(repo.resolve()) + _sha256_json({"requirements": requirements})).encode()).hexdigest()[:12]
def _now() -> str: return datetime.now(timezone.utc).isoformat()


@contextmanager
def _audit_lock(workspace: Path, timeout: float = 30.0):
    workspace.mkdir(parents=True, exist_ok=True)
    lock_path = workspace / ".audit.lock"
    with lock_path.open("a+b") as handle:
        if handle.tell() == 0 and lock_path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        _lock_file(handle, timeout=timeout)
        try:
            yield
        finally:
            _unlock_file(handle)


def _lock_file(handle, *, timeout: float = 30.0) -> None:
    if os.name == "nt":
        _lock_file_windows(handle, timeout=timeout)
    else:
        _lock_file_posix(handle)


def _unlock_file(handle) -> None:
    if os.name == "nt":
        _unlock_file_windows(handle)
    else:
        _unlock_file_posix(handle)


def _lock_file_posix(handle) -> None:
    import fcntl
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file_posix(handle) -> None:
    import fcntl
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _lock_file_windows(handle, *, timeout: float = 30.0) -> None:
    import msvcrt
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out acquiring audit lock") from exc
            time.sleep(0.05)


def _unlock_file_windows(handle) -> None:
    import msvcrt
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
