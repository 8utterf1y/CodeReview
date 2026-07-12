from __future__ import annotations

import hashlib
import json
import re
import fcntl
import sqlite3
import subprocess
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
        "counters": {"query": 0, "evidence": 0}, "created_at": _now(), "updated_at": _now(),
    }
    _write_json(workspace / "audit-state.json", state)
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
    state = _state(workspace)
    requirements = {item["id"]: item for item in _load_json(workspace / "requirements.json")["requirements"]}
    for req_id, item in state["requirements"].items():
        if item["investigation"] == "pending":
            requirement = requirements[req_id]
            return {
                "next_action": "investigate",
                "requirement_pack": requirement,
                "requirement": requirement,
                "code_hints": _code_hints_for_requirement(workspace, requirement),
                "worksheet": [
                    "STEP 1 explain the pack in repository terms",
                    "STEP 2 frame 1 to 3 implementation obligations",
                    "STEP 3 locate candidate code",
                    "STEP 4 inspect actual behavior",
                    "STEP 5 search alternatives or bypass paths",
                    "STEP 6 submit one conclusion",
                ],
            }
    for req_id, item in state["requirements"].items():
        if item["verification"] == "pending" and item["investigation"] == "submitted":
            return {"next_action": "review", "review_packet": review_bundle(workspace, req_id)}
    if state["assembly_allowed"]:
        return {"next_action": "finish" if state["stage"] != "assembled" else "done"}
    return {"next_action": "blocked", "reason": "audit state has no runnable transition", "status": audit_status(workspace)}


def submit_simple_investigation(workspace: Path, payload_path: Path) -> Dict[str, Any]:
    with _audit_lock(workspace):
        state = _state(workspace)
        payload = _load_json(payload_path)
        req_id = str(payload.get("requirement_id") or "")
        _require_requirement(state, req_id)
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
        _upsert(workspace / "investigations.json", "investigations", req_id, canonical)
        state["requirements"][req_id]["investigation"] = "submitted"
        state["requirements"][req_id]["verification"] = "pending" if conclusion == "mismatch" else "not_required"
        _refresh_stage(state)
        _save_state(workspace, state)
        return {"accepted": True, "requirement_id": req_id, "conclusion": conclusion, "next": next_action(workspace)}


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
        "claim": {
            "conclusion": investigation.get("agent_conclusion"), "status": investigation["proposed_status"],
            "summary": investigation["reasoning"], "issue": investigation.get("issue"),
            "obligations": investigation.get("obligations") or [],
            "findings": investigation.get("findings") or [],
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
        _upsert(workspace / "verifications.json", "verifications", req_id, canonical)
        state["requirements"][req_id]["verification"] = "submitted"
        _refresh_stage(state)
        _save_state(workspace, state)
        return {"accepted": True, "requirement_id": req_id, "verdict": verdict, "next": next_action(workspace)}


def finish_audit(workspace: Path) -> Dict[str, Any]:
    state = _state(workspace)
    output = state.get("requested_output")
    if not output:
        raise ValueError("audit was initialized without an output path")
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
    workspace: Path, requirement_id: str, role: str, mode: str, query: str = "",
    path: str = "", start: int = 1, end: int = 200, limit: int = 50,
) -> Dict[str, Any]:
    with _audit_lock(workspace):
        return _code_query(
            workspace, requirement_id, role, mode, query=query, path=path, start=start, end=end, limit=limit
        )


def _code_query(
    workspace: Path, requirement_id: str, role: str, mode: str, query: str = "",
    path: str = "", start: int = 1, end: int = 200, limit: int = 50,
) -> Dict[str, Any]:
    state = _state(workspace)
    _require_requirement(state, requirement_id)
    if role not in {"investigator", "verifier"}:
        raise ValueError("role must be investigator or verifier")
    requested_mode = mode
    mode = QUERY_MODE_ALIASES.get(mode.lower(), mode.lower())
    if mode not in {"concept", "source", "repo_map", "component", "build", "symbol", "references", "callers", "callees", "path", "data_flow"}:
        raise ValueError(f"unsupported query mode: {mode}")
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
    query_record = _record_query(
        workspace, state, requirement_id, role, mode,
        {"query": query, "path": path, "start": start, "end": end, "limit": limit,
         "requested_mode": requested_mode},
        [_materialize_result(repo, item) for item in results], tool_status, limitation,
        coverage=coverage,
    )
    return query_record


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
    _upsert(workspace / "investigations.json", "investigations", req_id, canonical)
    state["requirements"][req_id]["investigation"] = "submitted"
    state["requirements"][req_id]["verification"] = (
        "pending" if _verification_required(workspace, canonical) else "not_required"
    )
    _refresh_stage(state)
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
    _upsert(workspace / "verifications.json", "verifications", req_id, canonical)
    state["requirements"][req_id]["verification"] = "submitted"
    _refresh_stage(state)
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
        if status in {"violated", "partial"} and verification["verdict"] == "accepted" and investigation.get("issue"):
            issues.append(_assemble_issue(len(issues) + 1, req, investigation, verification, evidence_map))
        if status in {"unknown", "no_evidence_found", "non_verifiable"} or not verification_ok:
            unverified.append({"requirement_id": req_id, "status": status, "reason": verification["reasoning"]})
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
    _write_json(out, payload)
    sarif_out = out.with_suffix(".sarif")
    _write_sarif(sarif_out, payload)
    state["stage"] = "assembled"
    state["assembled_output"] = str(out.resolve())
    _save_state(workspace, state)
    return {"assembled": True, "out": str(out.resolve()), "sarif": str(sarif_out.resolve()), "issues": len(issues), "status_counts": dict(counts)}


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
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"rg query failed: {exc}") from exc
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


def _source_query(repo: Path, files: List[Dict[str, Any]], path: str, start: int, end: int) -> List[Dict[str, Any]]:
    item = next((row for row in files if row["path"] == path), None)
    if not item: raise ValueError(f"path is not indexed: {path}")
    lines = (repo / path).read_text(encoding="utf-8", errors="replace").splitlines()
    start, end = max(1, start), min(len(lines), max(start, end))
    return [{"file_id": item["file_id"], "path": path, "line": line_no, "quote": lines[line_no - 1][:500], "backend": "source_read", "precision": "exact_source"} for line_no in range(start, end + 1)]


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


def _record_query(workspace: Path, state: Dict[str, Any], req_id: str, role: str, mode: str, parameters: Dict[str, Any], results: List[Dict[str, Any]], tool_status: str, limitation: str, coverage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state["counters"]["query"] += 1
    query_id = f"Q-{state['counters']['query']:07d}"
    evidence_ids = []
    with (workspace / "evidence.jsonl").open("a", encoding="utf-8") as evidence_file:
        for result in results:
            if "path" not in result or "line" not in result: continue
            state["counters"]["evidence"] += 1
            evidence_id = f"E-{state['counters']['evidence']:08d}"
            evidence = {"evidence_id": evidence_id, "query_id": query_id, "requirement_id": req_id, **result}
            evidence_file.write(json.dumps(evidence, ensure_ascii=False) + "\n")
            evidence_ids.append(evidence_id)
    record = {"query_id": query_id, "requirement_id": req_id, "role": role, "mode": mode, "parameters": parameters, "status": tool_status, "limitation": limitation, "coverage": coverage or {}, "result_count": len(results), "evidence_ids": evidence_ids, "created_at": _now()}
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
    db_path = workspace / "code-index" / "codefacts.sqlite"
    if not db_path.exists():
        return {"components": [], "symbols": [], "source": "unavailable"}
    terms = _hint_terms(requirement)
    if not terms:
        return {"components": [], "symbols": [], "source": "sqlite_codefacts"}
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        symbol_scores: Counter[str] = Counter()
        component_scores: Counter[str] = Counter()
        for term in terms[:6]:
            pattern = f"%{term.lower()}%"
            for row in connection.execute(
                "SELECT name FROM symbols WHERE lower(name) LIKE ? LIMIT 20",
                (pattern,),
            ).fetchall():
                symbol_scores[row["name"]] += 1
            for row in connection.execute(
                "SELECT component FROM files WHERE lower(path) LIKE ? OR lower(component) LIKE ? LIMIT 20",
                (pattern, pattern),
            ).fetchall():
                component_scores[row["component"]] += 1
        return {
            "components": [name for name, _score in component_scores.most_common(component_limit)],
            "symbols": [name for name, _score in symbol_scores.most_common(symbol_limit)],
            "source": "sqlite_codefacts",
        }
    finally:
        connection.close()


def _hint_terms(requirement: Dict[str, Any]) -> List[str]:
    text = " ".join(
        str(requirement.get(field) or "")
        for field in ("document", "section", "quote", "normalized", "capability")
    )
    terms = list(requirement.get("keywords") or [])
    for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()):
        if term not in terms:
            terms.append(term)
    stop = {"rfc", "must", "should", "shall", "not", "for", "the", "and", "all", "section"}
    return [term for term in terms if term not in stop][:20]


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
    return not precisions or not precisions.issubset({"exact_source", "compiler_precise"})


def _assemble_issue(index: int, req: Dict[str, Any], investigation: Dict[str, Any], verification: Dict[str, Any], evidence_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    draft = investigation.get("issue") or {}
    evidence_ids = investigation["evidence_ids"]
    return {"id": f"ISSUE-{index:03d}", "requirement_id": req["id"], "title": draft.get("title") or req["normalized"], "match_type": draft.get("match_type") or investigation["proposed_status"], "severity": draft.get("severity") or "medium", "confidence": draft.get("confidence") or 0.6, "description": draft.get("description") or investigation["reasoning"], "spec_evidence": {"document": req.get("document"), "section": req.get("section"), "quote": req["quote"]}, "evidence_ids": evidence_ids, "code_evidence": [evidence_map[item] for item in evidence_ids if item in evidence_map], "verification": {"verdict": verification["verdict"], "reasoning": verification["reasoning"], "challenges": verification["challenges"]}}


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
def _audit_lock(workspace: Path):
    workspace.mkdir(parents=True, exist_ok=True)
    with (workspace / ".audit.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
