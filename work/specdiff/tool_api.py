from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from .code_index import CodeIndex
from .audit_runtime import (
    assemble_result,
    audit_requirements,
    audit_status,
    code_query,
    init_audit,
    finish_audit,
    next_action,
    review_bundle,
    submit_simple_investigation,
    submit_simple_review,
    submit_investigation,
    submit_verification,
    verification_context,
    verification_conclusion_context,
)
from .coverage import build_coverage_matrix, coverage_summary, rule_family_stats
from .coverage_gate import validate_result
from .generic_scanners import run_generic_scanners
from .investigation import (
    load_json,
    scaffold_requirement_models,
    validate_investigations,
    validate_requirement_models,
    validate_verifications,
)
from .spec_loader import extract_audit_requirements, extract_model_candidates, extract_requirements
from .rfc_prepare import prepare_rfc_requirements, write_prepared_requirements


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="specdiff-tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse-spec")
    p.add_argument("--docs", required=True)

    p = sub.add_parser("extract-requirements")
    p.add_argument("--docs", required=True)

    p = sub.add_parser("prepare-rfcs")
    p.add_argument("--inventory", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--max-per-rfc", type=_positive_int_or_default(0), default=0)
    p.add_argument("--offline", action="store_true")

    p = sub.add_parser("repo-map")
    p.add_argument("--repo", required=True)
    p.add_argument("--limit", type=_positive_int_or_default(120), default=120)

    p = sub.add_parser("code-search")
    p.add_argument("--repo", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--file-regex")
    p.add_argument("--limit", type=_positive_int_or_default(80), default=80)

    p = sub.add_parser("pattern-scan")
    p.add_argument("--repo", required=True)
    p.add_argument("--docs", required=True)
    p.add_argument("--limit", type=_positive_int_or_default(80), default=80)

    p = sub.add_parser("coverage-scan")
    p.add_argument("--repo", required=True)
    p.add_argument("--docs", required=True)
    p.add_argument("--limit", type=_positive_int_or_default(0), default=0)

    p = sub.add_parser("validate-result")
    p.add_argument("--result", required=True)

    p = sub.add_parser("scaffold-requirements")
    p.add_argument("--docs", required=True)

    p = sub.add_parser("validate-requirements")
    p.add_argument("--model", required=True)

    p = sub.add_parser("validate-investigation")
    p.add_argument("--model", required=True)
    p.add_argument("--investigation", required=True)

    p = sub.add_parser("validate-verification")
    p.add_argument("--model", required=True)
    p.add_argument("--investigation", required=True)
    p.add_argument("--verification", required=True)

    p = sub.add_parser("audit-init")
    p.add_argument("--repo", required=True)
    p.add_argument("--requirements", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--out")

    p = sub.add_parser("audit-next")
    p.add_argument("--workspace", required=True)

    p = sub.add_parser("audit-review-bundle")
    p.add_argument("--workspace", required=True)
    p.add_argument("--requirement-id", required=True)

    p = sub.add_parser("audit-submit-simple-investigation")
    p.add_argument("--workspace", required=True)
    p.add_argument("--payload", required=True)

    p = sub.add_parser("audit-submit-simple-review")
    p.add_argument("--workspace", required=True)
    p.add_argument("--payload", required=True)

    p = sub.add_parser("audit-finish")
    p.add_argument("--workspace", required=True)

    p = sub.add_parser("audit-status")
    p.add_argument("--workspace", required=True)

    p = sub.add_parser("audit-requirements")
    p.add_argument("--workspace", required=True)

    p = sub.add_parser("audit-query")
    p.add_argument("--workspace", required=True)
    p.add_argument("--requirement-id", required=True)
    p.add_argument("--role", choices=["investigator", "verifier"], required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--query", default="")
    p.add_argument("--path", default="")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=200)
    p.add_argument("--limit", type=_positive_int_or_default(50), default=50)

    p = sub.add_parser("audit-submit-investigation")
    p.add_argument("--workspace", required=True)
    p.add_argument("--payload", required=True)

    p = sub.add_parser("audit-submit-verification")
    p.add_argument("--workspace", required=True)
    p.add_argument("--payload", required=True)

    p = sub.add_parser("audit-verification-context")
    p.add_argument("--workspace", required=True)
    p.add_argument("--requirement-id", required=True)

    p = sub.add_parser("audit-verification-conclusion")
    p.add_argument("--workspace", required=True)
    p.add_argument("--requirement-id", required=True)

    p = sub.add_parser("audit-assemble")
    p.add_argument("--workspace", required=True)
    p.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "parse-spec":
            return _emit(_parse_spec(Path(args.docs)))
        if args.cmd == "extract-requirements":
            return _emit(_requirements_payload(extract_audit_requirements(Path(args.docs))))
        if args.cmd == "prepare-rfcs":
            payload = prepare_rfc_requirements(
                Path(args.inventory), Path(args.cache_dir),
                max_per_rfc=args.max_per_rfc or None, offline=args.offline,
            )
            write_prepared_requirements(payload, Path(args.out))
            return _emit({
                "prepared": True,
                "out": str(Path(args.out).resolve()),
                "artifact_type": payload.get("artifact_type"),
                "corpus_clauses": len(payload.get("clauses", [])),
                "requirement_packs": len(payload.get("requirement_packs", [])),
                "coverage": payload.get("coverage", {}),
                "sources": payload["sources"],
                "excluded_references": payload["excluded_references"],
                "limitations": payload["limitations"],
            })
        if args.cmd == "repo-map":
            return _emit(_repo_map(Path(args.repo), args.limit))
        if args.cmd == "code-search":
            return _emit(_code_search(Path(args.repo), args.query, args.file_regex, args.limit))
        if args.cmd == "pattern-scan":
            return _emit(_pattern_scan(Path(args.repo), Path(args.docs), args.limit))
        if args.cmd == "coverage-scan":
            return _emit(_coverage_scan(Path(args.repo), Path(args.docs), args.limit))
        if args.cmd == "validate-result":
            return _emit(validate_result(Path(args.result)))
        if args.cmd == "scaffold-requirements":
            return _emit(scaffold_requirement_models(extract_model_candidates(Path(args.docs))))
        if args.cmd == "validate-requirements":
            return _emit(validate_requirement_models(load_json(Path(args.model))))
        if args.cmd == "validate-investigation":
            return _emit(
                validate_investigations(
                    load_json(Path(args.investigation)), load_json(Path(args.model))
                )
            )
        if args.cmd == "validate-verification":
            return _emit(
                validate_verifications(
                    load_json(Path(args.verification)),
                    load_json(Path(args.model)),
                    load_json(Path(args.investigation)),
                )
            )
        if args.cmd == "audit-init":
            return _emit(init_audit(Path(args.repo), Path(args.requirements), Path(args.workspace), Path(args.out) if args.out else None))
        if args.cmd == "audit-next":
            return _emit(next_action(Path(args.workspace)))
        if args.cmd == "audit-review-bundle":
            return _emit(review_bundle(Path(args.workspace), args.requirement_id))
        if args.cmd == "audit-submit-simple-investigation":
            return _emit(submit_simple_investigation(Path(args.workspace), Path(args.payload)))
        if args.cmd == "audit-submit-simple-review":
            return _emit(submit_simple_review(Path(args.workspace), Path(args.payload)))
        if args.cmd == "audit-finish":
            return _emit(finish_audit(Path(args.workspace)))
        if args.cmd == "audit-status":
            return _emit(audit_status(Path(args.workspace)))
        if args.cmd == "audit-requirements":
            return _emit(audit_requirements(Path(args.workspace)))
        if args.cmd == "audit-query":
            return _emit(
                code_query(
                    Path(args.workspace), args.requirement_id, args.role, args.mode,
                    query=args.query, path=args.path, start=args.start, end=args.end, limit=args.limit,
                )
            )
        if args.cmd == "audit-submit-investigation":
            return _emit(submit_investigation(Path(args.workspace), Path(args.payload)))
        if args.cmd == "audit-submit-verification":
            return _emit(submit_verification(Path(args.workspace), Path(args.payload)))
        if args.cmd == "audit-verification-context":
            return _emit(verification_context(Path(args.workspace), args.requirement_id))
        if args.cmd == "audit-verification-conclusion":
            return _emit(verification_conclusion_context(Path(args.workspace), args.requirement_id))
        if args.cmd == "audit-assemble":
            return _emit(assemble_result(Path(args.workspace), Path(args.out)))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


def _positive_int_or_default(default: int):
    def parse(value: str) -> int:
        if value in ("", "undefined", "null", "None"):
            return default
        parsed = int(value)
        if parsed <= 0:
            return default
        return parsed

    return parse


def _parse_spec(path: Path) -> Dict[str, Any]:
    return _requirements_payload(extract_requirements(path))


def _requirements_payload(reqs) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_type": "parsed_requirements",
        "requirements": [
            {
                "id": req.id,
                "document": req.document,
                "section": req.section,
                "quote": req.quote,
                "normalized": req.normalized,
                "keywords": req.keywords,
                "source": req.source,
            }
            for req in reqs
        ]
    }


def _repo_map(repo: Path, limit: int) -> Dict[str, Any]:
    index = CodeIndex(repo)
    by_dir = Counter()
    by_ext = Counter()
    files = []
    for path in index.files:
        rel = index.rel(path)
        parts = rel.split("/")
        by_dir[parts[0] if len(parts) > 1 else "."] += 1
        by_ext[path.suffix or "<none>"] += 1
        if len(files) < limit:
            files.append(rel)
    return {
        "repo": str(repo.resolve()),
        "source_files_indexed": len(index.files),
        "top_directories": by_dir.most_common(25),
        "extensions": by_ext.most_common(25),
        "sample_files": files,
    }


def _code_search(repo: Path, query: str, file_regex: Optional[str], limit: int) -> Dict[str, Any]:
    index = CodeIndex(repo)
    hits = index.search(query, file_regex=file_regex, max_hits=limit)
    return {
        "query": query,
        "hits": [
            {"file": hit.file, "line": hit.line, "quote": hit.quote}
            for hit in hits
        ],
    }


def _pattern_scan(repo: Path, docs: Path, limit: int) -> Dict[str, Any]:
    reqs = extract_requirements(docs)
    index = CodeIndex(repo)
    candidates, _ = run_generic_scanners(index, reqs)
    return {
        "requirements_indexed": len(reqs),
        "source_files_indexed": len(index.files),
        "candidates": [candidate.to_dict() for candidate in candidates[:limit]],
    }


def _coverage_scan(repo: Path, docs: Path, limit: int) -> Dict[str, Any]:
    reqs = extract_requirements(docs)
    index = CodeIndex(repo)
    candidates, _ = run_generic_scanners(index, reqs)
    records, tool_status = build_coverage_matrix(index, reqs, [], candidates)
    if limit > 0:
        records = records[:limit]
    return {
        "requirements_indexed": len(reqs),
        "source_files_indexed": len(index.files),
        "coverage_summary": coverage_summary(records),
        "rule_family_stats": rule_family_stats(),
        "tool_status": [item.to_dict() for item in tool_status],
        "unverified_requirements": _unverified_requirements(records),
        "requirements": [record.to_dict() for record in records],
    }


def _emit(payload: Dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _unverified_requirements(records) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for record in records:
        if record.status in ("unknown", "no_evidence_found") or record.coverage_risk == "high":
            result.append(
                {
                    "id": record.requirement.id,
                    "status": record.status,
                    "rule_family": record.rule_family,
                    "coverage_risk": record.coverage_risk,
                    "reason": "; ".join(record.notes[:3]),
                }
            )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
