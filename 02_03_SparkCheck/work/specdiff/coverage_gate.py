from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .investigation import (
    load_json,
    validate_investigations,
    validate_requirement_models,
    validate_verifications,
)


LOW_SIGNAL_PATH = re.compile(
    r"(^|/)(doc|docs|test|tests|example|examples|contrib|firmware|tools/compat|compat/include)(/|$)",
    re.I,
)
HEADER_ONLY = re.compile(r"\.(h|hpp|hh)$", re.I)


def validate_result(result_path: Path) -> Dict[str, Any]:
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("artifact_type") == "assembled_audit":
        return _validate_assembled_result(result_path, payload)
    if payload.get("artifact_type") == "legacy_seed":
        return {
            "valid": False,
            "errors": ["legacy benchmark/hybrid output is seed evidence and cannot be accepted as a final audit"],
            "warnings": [],
            "checked_requirements": len(payload.get("requirements", [])),
        }
    errors: List[str] = []
    warnings: List[str] = []

    verification_ids = _validate_agent_review(result_path, payload, errors)
    _validate_verified_issues(payload, verification_ids, errors)
    _validate_unverified_requirements(payload, errors)
    for req in payload.get("requirements", []):
        _validate_requirement(req, errors, warnings)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_requirements": len(payload.get("requirements", [])),
    }


def _validate_assembled_result(result_path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    workspace_value = payload.get("audit_workspace")
    if not workspace_value:
        errors.append("assembled audit has no audit_workspace")
        return {"valid": False, "errors": errors, "warnings": warnings, "checked_requirements": 0}
    workspace = Path(str(workspace_value))
    state_path = workspace / "audit-state.json"
    if not state_path.exists():
        errors.append(f"assembled audit state does not exist: {state_path}")
        return {"valid": False, "errors": errors, "warnings": warnings, "checked_requirements": 0}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("audit_id") != payload.get("audit_id"):
        errors.append("assembled audit_id does not match controlled state")
    if state.get("stage") != "assembled" or not state.get("assembly_allowed"):
        errors.append("controlled audit state is not assembled/assembly_allowed")
    accepted_outputs = {
        Path(str(value)).resolve()
        for value in (state.get("assembled_output"), state.get("assembled_full_report"))
        if value
    }
    if result_path.resolve() not in accepted_outputs:
        errors.append("controlled audit state points to a different assembled output")

    query_ids = _jsonl_ids(workspace / "queries.jsonl", "query_id")
    evidence_ids = _jsonl_ids(workspace / "evidence.jsonl", "evidence_id")
    records = payload.get("requirements") or []
    for record in records:
        req = record.get("requirement") or {}
        req_id = str(req.get("id") or "")
        investigation = record.get("investigation") or {}
        verification = record.get("verification") or {}
        if investigation.get("requirement_id") != req_id or verification.get("requirement_id") != req_id:
            errors.append(f"{req_id}: assembled investigation/verification reference mismatch")
        for query_id in list(investigation.get("query_ids") or []) + list(investigation.get("counterexample_query_ids") or []) + list(verification.get("query_ids") or []):
            if query_id not in query_ids:
                errors.append(f"{req_id}: unknown assembled query id: {query_id}")
        for evidence_id in list(investigation.get("evidence_ids") or []) + list(verification.get("evidence_ids") or []):
            if evidence_id not in evidence_ids:
                errors.append(f"{req_id}: unknown assembled evidence id: {evidence_id}")
        verdict = verification.get("verdict")
        if record.get("status") in {"violated", "partial"} and verdict != "accepted":
            errors.append(f"{req_id}: divergence status lacks accepted verification")
        if record.get("status") == "covered" and verdict not in {"accepted", "not_required"}:
            errors.append(f"{req_id}: covered status lacks accepted or explicitly waived verification")
    valid_req_ids = {str((item.get("requirement") or {}).get("id") or "") for item in records}
    for issue in payload.get("issues") or []:
        if str(issue.get("requirement_id") or "") not in valid_req_ids:
            errors.append(f"{issue.get('id', 'issue')}: references an unknown requirement")
        for evidence_id in issue.get("evidence_ids") or []:
            if evidence_id not in evidence_ids:
                errors.append(f"{issue.get('id', 'issue')}: references unknown evidence: {evidence_id}")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "checked_requirements": len(records)}


def _jsonl_ids(path: Path, key: str) -> set[str]:
    if not path.exists():
        return set()
    return {
        str(item.get(key))
        for item in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        if item.get(key)
    }


def _validate_agent_review(result_path: Path, payload: Dict[str, Any], errors: List[str]) -> set[str]:
    review = payload.get("agent_review") or {}
    status = review.get("status")
    artifacts = review.get("artifacts") or {}
    if artifacts:
        return _validate_proof_artifacts(result_path, status, artifacts, errors)
    artifact = review.get("artifact")
    if status == "completed":
        if not artifact:
            errors.append("agent_review.status is completed but no artifact is declared")
            return set()
        artifact_path = Path(artifact)
        if not artifact_path.is_absolute():
            artifact_path = result_path.parent / artifact_path.name
        if not artifact_path.exists():
            errors.append(f"agent_review.status is completed but artifact does not exist: {artifact}")
    return set()


def _validate_proof_artifacts(
    result_path: Path, status: str, artifacts: Dict[str, Any], errors: List[str]
) -> set[str]:
    required = ("requirements", "investigation", "verification")
    paths: Dict[str, Path] = {}
    for name in required:
        value = artifacts.get(name)
        if not value:
            if status == "completed":
                errors.append(f"agent_review.status is completed but {name} artifact is missing")
            continue
        path = Path(str(value))
        if not path.is_absolute():
            path = result_path.parent / path.name
        if not path.exists():
            errors.append(f"agent_review {name} artifact does not exist: {value}")
            continue
        paths[name] = path
    if len(paths) != len(required):
        return set()

    models = load_json(paths["requirements"])
    investigations = load_json(paths["investigation"])
    verifications = load_json(paths["verification"])
    validations = (
        ("requirements", validate_requirement_models(models)),
        ("investigation", validate_investigations(investigations, models)),
        ("verification", validate_verifications(verifications, models, investigations)),
    )
    for name, validation in validations:
        for message in validation["errors"]:
            errors.append(f"{name} artifact: {message}")
    return {
        str(item.get("requirement_id"))
        for item in verifications.get("verifications", [])
        if isinstance(item, dict) and item.get("verdict") == "accepted"
    }


def _validate_verified_issues(
    payload: Dict[str, Any], verification_ids: set[str], errors: List[str]
) -> None:
    review = payload.get("agent_review") or {}
    if not review.get("artifacts"):
        return
    for issue in payload.get("issues", []):
        req_id = str(issue.get("requirement_id") or "")
        issue_id = str(issue.get("id") or "issue")
        if not req_id:
            errors.append(f"{issue_id}: proof-driven issue has no requirement_id")
        elif req_id not in verification_ids:
            errors.append(f"{issue_id}: requirement {req_id} was not accepted by independent verification")


def _validate_requirement(req: Dict[str, Any], errors: List[str], warnings: List[str]) -> None:
    req_id = str(req.get("id") or req.get("requirement", {}).get("id") or "")
    status = str(req.get("status") or "")
    evidence = req.get("positive_evidence") or []
    allowed = {"covered", "violated", "partial", "no_evidence_found", "unknown", "out_of_scope", "non_verifiable"}
    if status and status not in allowed:
        errors.append(f"{req_id}: invalid coverage status: {status}")

    if status == "covered":
        _validate_search_completeness(req_id, req, errors)
        ok, reason = _covered_has_execution_evidence(req_id, evidence)
        if not ok:
            errors.append(f"{req_id}: covered status lacks execution-path evidence: {reason}")
        if _evidence_mentions_negative_behavior(evidence):
            errors.append(f"{req_id}: covered status uses evidence that appears to describe missing, TODO, unsupported, or incomplete behavior")


def _validate_search_completeness(req_id: str, req: Dict[str, Any], errors: List[str]) -> None:
    plan = req.get("search_plan") or {}
    trace = req.get("search_trace") or []
    if not plan or not trace:
        errors.append(f"{req_id}: covered status has no search plan/trace")
        return
    trace_by_dimension = {str(item.get("dimension") or ""): item for item in trace if isinstance(item, dict)}
    for dimension in plan.get("dimensions") or []:
        if not dimension.get("required_for_covered", True):
            continue
        name = str(dimension.get("name") or "")
        item = trace_by_dimension.get(name)
        if not item or item.get("status") != "completed_with_hits":
            errors.append(f"{req_id}: covered status lacks completed evidence for search dimension: {name}")


def _validate_unverified_requirements(payload: Dict[str, Any], errors: List[str]) -> None:
    unverified = payload.get("unverified_requirements") or []
    unverified_ids = {
        str(item.get("id") or item.get("requirement_id") or "")
        for item in unverified
        if isinstance(item, dict)
    }
    for req in payload.get("requirements", []):
        req_id = str(req.get("id") or req.get("requirement", {}).get("id") or "")
        status = str(req.get("status") or "")
        risk = str(req.get("coverage_risk") or "")
        if status in {"unknown", "no_evidence_found"} or risk == "high":
            if req_id not in unverified_ids:
                errors.append(f"{req_id}: {status}/{risk} requirement is missing from unverified_requirements")


def _covered_has_execution_evidence(req_id: str, evidence: List[Dict[str, Any]]) -> Tuple[bool, str]:
    if not evidence:
        return False, "no positive evidence"
    has_execution = False
    weak_only = True
    for item in evidence:
        file = str(item.get("file") or "")
        quote = str(item.get("quote") or "")
        if LOW_SIGNAL_PATH.search(file):
            continue
        if _quote_is_comment_or_constant(quote):
            continue
        if not HEADER_ONLY.search(file):
            weak_only = False
        if re.search(r"\b(if|for|while|switch|case|return|callout|enqueue|input|output|dispatch|register)\b|[A-Za-z_][A-Za-z0-9_]*\s*\(", quote):
            has_execution = True
    if weak_only:
        return False, "only low-signal/header evidence"
    if not has_execution:
        return False, "no function, branch, dispatch, or call evidence"
    return True, ""


def _quote_is_comment_or_constant(quote: str) -> bool:
    stripped = quote.strip()
    if stripped.startswith(("//", "/*", "*")):
        return True
    return bool(re.match(r"^\s*#\s*define\b", stripped))


def _evidence_mentions_negative_behavior(evidence: List[Dict[str, Any]]) -> bool:
    parts = []
    for item in evidence:
        parts.append(str(item.get("quote") or ""))
        parts.append(str(item.get("note") or ""))
    blob = " ".join(parts)
    return bool(
        re.search(
            r"not implemented|todo|fixme|unsupported|doesn.?t|does not|missing|incomplete|only looks|not follow",
            blob,
            re.I,
        )
    )
