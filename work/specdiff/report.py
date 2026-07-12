from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Sequence

from .models import CoverageRecord, Finding


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, findings: List[Finding], coverage: Sequence[CoverageRecord] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# SpecDiff Report",
        "",
        f"Detected issues: {len(findings)}",
        "",
    ]
    if coverage:
        coverage_counts: Dict[str, int] = {}
        for record in coverage:
            coverage_counts[record.status] = coverage_counts.get(record.status, 0) + 1
        lines.extend(
            [
                f"Requirements reviewed: {len(coverage)}",
                f"Coverage status counts: {coverage_counts}",
                "",
                "## Coverage Matrix",
                "",
                "| Requirement | Rule Family | Status | Strength | Risk | Evidence |",
                "|---|---|---:|---:|---:|---|",
            ]
        )
        for record in coverage:
            evidence = record.positive_evidence[0].quote if record.positive_evidence else "; ".join(record.missing_evidence_searches[:1])
            lines.append(
                f"| {record.requirement.id} | {record.rule_family} | {record.status} | {record.evidence_strength} | {record.coverage_risk} | {evidence[:120]} |"
            )
        lines.extend(["", "## Issues", ""])
    for finding in findings:
        lines.extend(
            [
                f"## {finding.id}: {finding.title}",
                "",
                f"- Severity: {finding.severity}",
                f"- Confidence: {finding.confidence:.2f}",
                f"- Match type: {finding.match_type}",
                f"- Description: {finding.description}",
                "",
                "Spec evidence:",
                "",
                f"- Document: {finding.spec_evidence.document or 'unknown'}",
                f"- Section: {finding.spec_evidence.section or 'unknown'}",
                f"- Quote: {finding.spec_evidence.quote}",
                "",
                "Code evidence:",
                "",
                f"- File: {finding.code_evidence.file or 'repository scan'}",
                f"- Line: {finding.code_evidence.line or 'n/a'}",
                f"- Quote: {finding.code_evidence.quote}",
                "",
                "Verification:",
            ]
        )
        for item in finding.verification:
            lines.append(f"- {item}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
