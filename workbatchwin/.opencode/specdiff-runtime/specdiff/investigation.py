from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .models import Requirement


RESPONSIBILITY_STATUSES = {"confirmed", "unresolved", "out_of_scope", "non_verifiable"}
OBLIGATION_STATUSES = {"supported", "contradicted", "unresolved", "not_applicable"}
VERIFICATION_VERDICTS = {"accepted", "rejected", "needs_more_work"}


def scaffold_requirement_models(requirements: Sequence[Requirement]) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_type": "requirement_models",
        "instructions": (
            "An agent must complete interpretation, responsibility, behavior_model, proof_obligations, "
            "and uncertainties from specification context. Empty scaffolds are not audit conclusions."
        ),
        "requirements": [_requirement_scaffold(item) for item in requirements],
    }


def validate_requirement_models(payload: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    requirements = payload.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        errors.append("requirements must be a non-empty list")
        requirements = []

    seen = set()
    for item in requirements:
        req_id = str(item.get("id") or "") if isinstance(item, dict) else ""
        if not req_id:
            errors.append("requirement model has no id")
            continue
        if req_id in seen:
            errors.append(f"{req_id}: duplicate requirement id")
        seen.add(req_id)
        _validate_requirement_model(req_id, item, errors, warnings)

    return _validation(errors, warnings, len(requirements))


def validate_investigations(payload: Dict[str, Any], models: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    model_map = {item["id"]: item for item in models.get("requirements", []) if isinstance(item, dict) and item.get("id")}
    investigations = payload.get("investigations")
    if not isinstance(investigations, list):
        errors.append("investigations must be a list")
        investigations = []
    investigation_map = {
        item.get("requirement_id"): item
        for item in investigations
        if isinstance(item, dict) and item.get("requirement_id")
    }

    for req_id, model in model_map.items():
        responsibility = (model.get("responsibility") or {}).get("status")
        if responsibility in {"out_of_scope", "non_verifiable"}:
            continue
        investigation = investigation_map.get(req_id)
        if not investigation:
            errors.append(f"{req_id}: missing investigation")
            continue
        _validate_investigation(req_id, model, investigation, errors, warnings)

    for req_id in investigation_map:
        if req_id not in model_map:
            errors.append(f"{req_id}: investigation references an unknown requirement")
    return _validation(errors, warnings, len(investigations))


def validate_verifications(
    payload: Dict[str, Any], models: Dict[str, Any], investigations: Dict[str, Any]
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    model_ids = {item.get("id") for item in models.get("requirements", []) if isinstance(item, dict)}
    investigation_ids = {
        item.get("requirement_id")
        for item in investigations.get("investigations", [])
        if isinstance(item, dict)
    }
    verifications = payload.get("verifications")
    if not isinstance(verifications, list):
        errors.append("verifications must be a list")
        verifications = []
    verification_ids = set()
    for item in verifications:
        if not isinstance(item, dict):
            errors.append("verification entry must be an object")
            continue
        req_id = str(item.get("requirement_id") or "")
        verification_ids.add(req_id)
        if req_id not in model_ids:
            errors.append(f"{req_id}: verification references an unknown requirement")
        verdict = item.get("verdict")
        if verdict not in VERIFICATION_VERDICTS:
            errors.append(f"{req_id}: invalid verification verdict: {verdict}")
        if not isinstance(item.get("challenges"), list):
            errors.append(f"{req_id}: challenges must be a list")
        if verdict == "accepted" and not item.get("reasoning"):
            errors.append(f"{req_id}: accepted verification lacks reasoning")

    missing = investigation_ids - verification_ids
    for req_id in sorted(item for item in missing if item):
        errors.append(f"{req_id}: investigation has no independent verification")
    return _validation(errors, warnings, len(verifications))


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _requirement_scaffold(req: Requirement) -> Dict[str, Any]:
    return {
        "id": req.id,
        "source": {
            "document": req.document,
            "section": req.section,
            "quote": req.quote,
            "normalized": req.normalized,
            "source_kind": req.source,
        },
        "interpretation": {
            "statement": "",
            "normative_level": "unresolved",
            "conditions": [],
            "exceptions": [],
            "scope_notes": [],
        },
        "responsibility": {
            "status": "unresolved",
            "expected_components": [],
            "reasoning": "",
            "must_resolve_before_missing_finding": True,
        },
        "behavior_model": {
            "triggers": [],
            "preconditions": [],
            "required_actions": [],
            "forbidden_behaviors": [],
            "observable_effects": [],
            "failure_behaviors": [],
        },
        "proof_obligations": [],
        "uncertainties": [],
        "inferred": False,
    }


def _validate_requirement_model(
    req_id: str, item: Dict[str, Any], errors: List[str], warnings: List[str]
) -> None:
    source = item.get("source") or {}
    if not source.get("document") or not source.get("quote"):
        errors.append(f"{req_id}: source document and quote are required")
    interpretation = item.get("interpretation") or {}
    if not interpretation.get("statement"):
        errors.append(f"{req_id}: interpretation.statement is empty")
    responsibility = item.get("responsibility") or {}
    status = responsibility.get("status")
    if status not in RESPONSIBILITY_STATUSES:
        errors.append(f"{req_id}: invalid responsibility status: {status}")
    if status == "confirmed" and not responsibility.get("reasoning"):
        errors.append(f"{req_id}: confirmed responsibility lacks reasoning")

    behavior = item.get("behavior_model") or {}
    behavior_fields = ("triggers", "required_actions", "forbidden_behaviors", "observable_effects")
    if status == "confirmed" and not any(behavior.get(field) for field in behavior_fields):
        errors.append(f"{req_id}: confirmed requirement has an empty behavior model")

    obligations = item.get("proof_obligations")
    if not isinstance(obligations, list):
        errors.append(f"{req_id}: proof_obligations must be a list")
        return
    if status == "confirmed" and not obligations:
        errors.append(f"{req_id}: confirmed requirement has no proof obligations")
    obligation_ids = set()
    for obligation in obligations:
        obligation_id = str(obligation.get("id") or "") if isinstance(obligation, dict) else ""
        if not obligation_id:
            errors.append(f"{req_id}: proof obligation has no id")
            continue
        if obligation_id in obligation_ids:
            errors.append(f"{req_id}: duplicate proof obligation id: {obligation_id}")
        obligation_ids.add(obligation_id)
        for field in ("claim", "kind", "success_condition", "contradiction_condition"):
            if not obligation.get(field):
                errors.append(f"{req_id}/{obligation_id}: missing {field}")
        if not isinstance(obligation.get("evidence_needed"), list) or not obligation.get("evidence_needed"):
            errors.append(f"{req_id}/{obligation_id}: evidence_needed must be a non-empty list")
    if status == "unresolved":
        warnings.append(f"{req_id}: responsibility remains unresolved; missing_in_code is forbidden")


def _validate_investigation(
    req_id: str,
    model: Dict[str, Any],
    investigation: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> None:
    expected = {item.get("id") for item in model.get("proof_obligations", []) if isinstance(item, dict)}
    results = investigation.get("obligation_results")
    if not isinstance(results, list):
        errors.append(f"{req_id}: obligation_results must be a list")
        return
    result_map = {item.get("obligation_id"): item for item in results if isinstance(item, dict)}
    for obligation_id in expected:
        if obligation_id not in result_map:
            errors.append(f"{req_id}/{obligation_id}: missing investigation result")
            continue
        result = result_map[obligation_id]
        status = result.get("status")
        if status not in OBLIGATION_STATUSES:
            errors.append(f"{req_id}/{obligation_id}: invalid status: {status}")
        queries = result.get("queries")
        if not isinstance(queries, list) or not queries:
            errors.append(f"{req_id}/{obligation_id}: no query trace")
        else:
            for index, query in enumerate(queries, 1):
                if not isinstance(query, dict) or not query.get("type") or not query.get("purpose"):
                    errors.append(f"{req_id}/{obligation_id}: query {index} lacks type or purpose")
        if status in {"supported", "contradicted"} and not result.get("evidence"):
            errors.append(f"{req_id}/{obligation_id}: {status} result lacks evidence")
        if status == "unresolved":
            warnings.append(f"{req_id}/{obligation_id}: proof obligation remains unresolved")
    extra = set(result_map) - expected
    for obligation_id in sorted(item for item in extra if item):
        errors.append(f"{req_id}/{obligation_id}: result references unknown proof obligation")

    proposed = investigation.get("proposed_status")
    if proposed == "violated" and (model.get("responsibility") or {}).get("status") != "confirmed":
        errors.append(f"{req_id}: violated is forbidden until repository responsibility is confirmed")
    if proposed == "covered":
        unresolved = [item for item in results if item.get("status") != "supported"]
        if unresolved:
            errors.append(f"{req_id}: covered requires every proof obligation to be supported")
        if not investigation.get("counterexample_searches"):
            errors.append(f"{req_id}: covered requires counterexample_searches")


def _validation(errors: List[str], warnings: List[str], checked: int) -> Dict[str, Any]:
    return {"valid": not errors, "errors": errors, "warnings": warnings, "checked": checked}
