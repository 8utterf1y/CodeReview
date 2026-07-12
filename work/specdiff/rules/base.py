from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from ..models import Evidence, Requirement


@dataclass(frozen=True)
class RuleFamily:
    name: str
    description: str
    requirement_terms: Sequence[str]
    strong_evidence: Sequence[str]
    medium_evidence: Sequence[str]
    weak_evidence: Sequence[str]
    covered_requires: str


@dataclass
class EvidenceAssessment:
    family: RuleFamily
    strength: str
    status: str
    confidence: float
    coverage_risk: str
    notes: List[str] = field(default_factory=list)

    def to_notes(self) -> List[str]:
        return [
            f"rule_family={self.family.name}",
            f"evidence_strength={self.strength}",
            *self.notes,
        ]


def requirement_blob(requirement: Requirement) -> str:
    return " ".join(
        [
            requirement.id,
            requirement.document,
            requirement.section,
            requirement.quote,
            requirement.normalized,
            " ".join(_flatten_strings(requirement.keywords)),
        ]
    ).lower()


def evidence_blob(evidence: Sequence[Evidence]) -> str:
    parts: List[str] = []
    for item in evidence:
        parts.extend([str(item.file or ""), str(item.quote or ""), str(item.note or "")])
    return " ".join(parts).lower()


def evidence_paths(evidence: Sequence[Evidence]) -> List[str]:
    return [str(item.file or "") for item in evidence if item.file]


def summarize_families(families: Sequence[RuleFamily]) -> Dict[str, Dict[str, object]]:
    return {
        family.name: {
            "description": family.description,
            "strong_evidence": list(family.strong_evidence),
            "medium_evidence": list(family.medium_evidence),
            "weak_evidence": list(family.weak_evidence),
            "covered_requires": family.covered_requires,
        }
        for family in families
    }


def _flatten_strings(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            result.extend(_flatten_strings(value))
        else:
            result.append(str(value))
    return result
