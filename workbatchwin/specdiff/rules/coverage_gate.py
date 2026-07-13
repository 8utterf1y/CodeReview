from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from ..models import Candidate, Evidence, Finding, Requirement
from .base import EvidenceAssessment, RuleFamily, evidence_blob, evidence_paths


LOW_SIGNAL_PATH = re.compile(
    r"(^|/)(doc|docs|test|tests|example|examples|contrib|vendor|third_party|firmware|tools/compat|compat/include)(/|$)",
    re.I,
)
HEADER_ONLY = re.compile(r"\.(h|hpp|hh)$", re.I)
COMMENT_OR_DECLARATION = re.compile(
    r"^\s*(//|/\*|\*|#\s*define\b|typedef\b|enum\b|struct\b|class\b|interface\b)",
    re.I,
)
NEGATIVE_BEHAVIOR = re.compile(
    r"not implemented|todo|fixme|unsupported|doesn.?t|does not|missing|incomplete|only looks|not follow|stub",
    re.I,
)
EXECUTION_SIGNAL = re.compile(
    r"\b(if|for|while|switch|case|return|throw|catch|try|callout|enqueue|dequeue|input|output|dispatch|register|"
    r"emit|send|recv|receive|handle|validate|authorize|authenticate|open|close|free|release|lock|unlock)\b|"
    r"[A-Za-z_][A-Za-z0-9_]*\s*\(",
    re.I,
)


def evaluate_coverage(
    requirement: Requirement,
    family: RuleFamily,
    evidence: Sequence[Evidence],
    findings: Sequence[Finding],
    candidates: Sequence[Candidate],
) -> EvidenceAssessment:
    if findings:
        return EvidenceAssessment(
            family=family,
            strength="strong",
            status="violated",
            confidence=max(item.confidence for item in findings),
            coverage_risk="low",
            notes=["final issue exists for this requirement"],
        )

    strength, strength_notes = assess_evidence_strength(family, evidence)
    strong_candidates = [item for item in candidates if item.confidence >= 0.7]
    if strong_candidates:
        return EvidenceAssessment(
            family=family,
            strength=max(strength, "medium", key=_strength_rank),
            status="partial",
            confidence=max(item.confidence for item in strong_candidates),
            coverage_risk="medium",
            notes=["strong candidate requires verification before final reporting", *strength_notes],
        )

    if not evidence:
        return EvidenceAssessment(
            family=family,
            strength="none",
            status="no_evidence_found",
            confidence=0.2,
            coverage_risk="high",
            notes=["no implementation evidence found by available tools"],
        )

    if strength == "strong":
        return EvidenceAssessment(
            family=family,
            strength=strength,
            status="covered",
            confidence=0.72,
            coverage_risk="low",
            notes=strength_notes,
        )
    if strength == "medium":
        return EvidenceAssessment(
            family=family,
            strength=strength,
            status="unknown",
            confidence=0.45,
            coverage_risk="medium",
            notes=["medium evidence exists, but coverage gate needs stronger behavior-path proof", *strength_notes],
        )
    return EvidenceAssessment(
        family=family,
        strength=strength,
        status="unknown",
        confidence=0.3,
        coverage_risk="high",
        notes=["only weak evidence exists; cannot prove coverage", *strength_notes],
    )


def assess_evidence_strength(family: RuleFamily, evidence: Sequence[Evidence]) -> Tuple[str, List[str]]:
    blob = evidence_blob(evidence)
    paths = evidence_paths(evidence)
    notes: List[str] = []

    if NEGATIVE_BEHAVIOR.search(blob):
        return "weak", ["evidence mentions missing, unsupported, incomplete, or TODO behavior"]

    production = [path for path in paths if path and not LOW_SIGNAL_PATH.search(path)]
    non_header = [path for path in production if not HEADER_ONLY.search(path)]
    execution = [item for item in evidence if _has_execution_signal(item)]

    strong_hits = _count_terms(blob, family.strong_evidence)
    medium_hits = _count_terms(blob, family.medium_evidence)
    weak_hits = _count_terms(blob, family.weak_evidence)

    if not production:
        return "weak", ["evidence is only docs/tests/examples/vendor/compat or has no code path"]
    if not non_header:
        return "weak", ["evidence is header-only; needs implementation path"]
    if not execution:
        return "weak", ["no function, branch, call, dispatch, or behavior-path evidence"]
    if strong_hits >= 1 and (medium_hits >= 1 or len(execution) >= 2):
        return "strong", [f"passed global and family gate for {family.name}"]
    if medium_hits >= 1 or len(execution) >= 1:
        notes.append(f"medium evidence for {family.name}; covered requires {family.covered_requires}")
        if weak_hits:
            notes.append("weak signals also present; do not treat them as sufficient")
        return "medium", notes
    return "weak", [f"no family-specific evidence for {family.name}"]


def validate_covered_record(requirement_id: str, evidence: Sequence[Evidence], family: RuleFamily) -> Tuple[bool, str]:
    strength, notes = assess_evidence_strength(family, evidence)
    if strength != "strong":
        return False, "; ".join(notes)
    return True, ""


def _has_execution_signal(item: Evidence) -> bool:
    quote = item.quote or ""
    if COMMENT_OR_DECLARATION.search(quote.strip()):
        return False
    return bool(EXECUTION_SIGNAL.search(quote))


def _count_terms(blob: str, terms: Sequence[str]) -> int:
    return sum(1 for term in terms if term.lower() in blob)


def _strength_rank(value: str) -> int:
    return {"none": 0, "weak": 1, "medium": 2, "strong": 3}.get(value, 0)
