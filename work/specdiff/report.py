from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from .models import Finding


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, findings: List[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# SpecDiff Report",
        "",
        f"Detected issues: {len(findings)}",
        "",
    ]
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
