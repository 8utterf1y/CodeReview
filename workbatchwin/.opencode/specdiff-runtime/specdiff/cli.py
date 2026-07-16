from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
<<<<<<< HEAD
=======
from .checkers import run_all_checkers
>>>>>>> bc85301 (workbatchwin)
from .code_index import CodeIndex
from .coverage import build_coverage_matrix, coverage_summary, rule_family_stats
from .generic_scanners import run_generic_scanners
from .report import write_json, write_markdown
from .spec_loader import extract_requirements


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="specdiff",
        description="Detect inconsistencies between design/RFC documents and code implementations.",
    )
    parser.add_argument("--repo", required=True, help="Path to the implementation repository.")
    parser.add_argument("--docs", required=True, help="Path to a spec/design document file or directory.")
    parser.add_argument("--out", required=True, help="Path to write machine-readable issues JSON.")
    parser.add_argument("--report", help="Optional path to write a Markdown report.")
    parser.add_argument(
        "--candidates-out",
        help="Optional path to write generic scanner candidates for OpenCode/agent alignment.",
    )
    parser.add_argument(
        "--coverage-out",
        help="Optional path to write per-requirement coverage matrix for OpenCode/agent verification.",
    )
    parser.add_argument(
        "--mode",
<<<<<<< HEAD
        choices=["generic"],
        default="generic",
        help="Run reusable generic candidate scanners. The OpenCode audit path uses the batch runtime.",
=======
        choices=["benchmark", "generic", "hybrid"],
        default="generic",
        help=(
            "benchmark runs high-confidence benchmark/RFC checkers; generic runs reusable candidate scanners; "
            "hybrid runs both. The default is generic."
        ),
>>>>>>> bc85301 (workbatchwin)
    )
    parser.add_argument(
        "--promote-generic",
        action="store_true",
        help="Promote high-confidence generic scanner candidates into final issues. Useful for OpenCode-reviewed runs.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Only emit findings with confidence greater than or equal to this value.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    docs = Path(args.docs).resolve()
    out = Path(args.out).resolve()
    report = Path(args.report).resolve() if args.report else None
    candidates_out = Path(args.candidates_out).resolve() if args.candidates_out else None
    coverage_out = Path(args.coverage_out).resolve() if args.coverage_out else None

    try:
<<<<<<< HEAD
        requirements = extract_requirements(docs)
=======
        requirements = extract_requirements(docs, include_builtin_hints=args.mode in ("benchmark", "hybrid"))
>>>>>>> bc85301 (workbatchwin)
        index = CodeIndex(repo)
        findings = []
        candidates = []
        generic_findings = []

<<<<<<< HEAD
        candidates, generic_findings = run_generic_scanners(index, requirements)
        if args.promote_generic:
            findings.extend(generic_findings)
=======
        if args.mode in ("benchmark", "hybrid"):
            findings.extend(run_all_checkers(index, requirements))
        if args.mode in ("generic", "hybrid"):
            candidates, generic_findings = run_generic_scanners(index, requirements)
            if args.promote_generic:
                findings.extend(generic_findings)
>>>>>>> bc85301 (workbatchwin)

        findings = [
            finding
            for finding in _renumber_findings(_dedupe_findings(findings))
            if finding.confidence >= args.min_confidence
        ]
        coverage_records, tool_status = build_coverage_matrix(index, requirements, findings, candidates)
        cov_summary = coverage_summary(coverage_records)
        unverified = _unverified_requirements(coverage_records)
        payload = {
            "tool": "specdiff",
<<<<<<< HEAD
            "artifact_type": "candidate_seed",
=======
            "artifact_type": "legacy_seed" if args.mode in ("benchmark", "hybrid") else "candidate_seed",
>>>>>>> bc85301 (workbatchwin)
            "version": __version__,
            "mode": args.mode,
            "repo": str(repo),
            "docs": str(docs),
            "requirements_indexed": len(requirements),
            "source_files_indexed": len(index.files),
            "candidates_count": len(candidates),
            "coverage_summary": cov_summary,
            "rule_family_stats": rule_family_stats(),
            "tool_status": [item.to_dict() for item in tool_status],
            "requirements": [record.to_dict() for record in coverage_records],
            "unverified_requirements": unverified,
            "issues": [finding.to_dict() for finding in findings],
        }
        write_json(out, payload)
        if candidates_out:
            write_json(
                candidates_out,
                {
                    "tool": "specdiff",
                    "version": __version__,
                    "mode": args.mode,
                    "repo": str(repo),
                    "docs": str(docs),
                    "requirements_indexed": len(requirements),
                    "source_files_indexed": len(index.files),
                    "candidates": [candidate.to_dict() for candidate in candidates],
                },
            )
        if report:
            write_markdown(report, findings, coverage_records)
        if coverage_out:
            write_json(
                coverage_out,
                {
                    "tool": "specdiff",
                    "version": __version__,
                    "mode": args.mode,
                    "repo": str(repo),
                    "docs": str(docs),
                    "coverage_summary": cov_summary,
                    "rule_family_stats": rule_family_stats(),
                    "tool_status": [item.to_dict() for item in tool_status],
                    "unverified_requirements": unverified,
                    "requirements": [record.to_dict() for record in coverage_records],
                },
            )
    except Exception as exc:
        print(f"specdiff error: {exc}", file=sys.stderr)
        return 2
    return 0


def _dedupe_findings(findings):
    seen = set()
    result = []
    for finding in sorted(findings, key=lambda item: item.confidence, reverse=True):
        key = (finding.title, finding.code_evidence.file, finding.code_evidence.line, finding.spec_evidence.document)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result


def _renumber_findings(findings):
    for idx, finding in enumerate(findings, 1):
        finding.id = f"ISSUE-{idx:03d}"
    return findings


def _unverified_requirements(records):
    result = []
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
