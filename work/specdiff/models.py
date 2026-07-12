from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Evidence:
    document: Optional[str] = None
    section: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    quote: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value not in (None, "", [])}


@dataclass
class Requirement:
    id: str
    document: str
    section: str
    quote: str
    normalized: str
    keywords: List[str] = field(default_factory=list)
    source: str = "document"

    def evidence(self) -> Evidence:
        return Evidence(document=self.document, section=self.section, quote=self.quote)


@dataclass
class CodeHit:
    file: str
    line: int
    quote: str

    def evidence(self, note: str = "") -> Evidence:
        return Evidence(file=self.file, line=self.line, quote=self.quote, note=note)


@dataclass
class Finding:
    id: str
    title: str
    match_type: str
    severity: str
    confidence: float
    description: str
    spec_evidence: Evidence
    code_evidence: Evidence
    verification: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "match_type": self.match_type,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "description": self.description,
            "spec_evidence": self.spec_evidence.to_dict(),
            "code_evidence": self.code_evidence.to_dict(),
            "verification": self.verification,
        }


@dataclass
class Candidate:
    id: str
    scanner: str
    category: str
    title: str
    confidence: float
    requirement: Requirement
    evidence: Evidence
    rationale: str
    next_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "scanner": self.scanner,
            "category": self.category,
            "title": self.title,
            "confidence": round(self.confidence, 3),
            "requirement": {
                "id": self.requirement.id,
                "document": self.requirement.document,
                "section": self.requirement.section,
                "quote": self.requirement.quote,
                "normalized": self.requirement.normalized,
                "keywords": self.requirement.keywords,
                "source": self.requirement.source,
            },
            "evidence": self.evidence.to_dict(),
            "rationale": self.rationale,
            "next_steps": self.next_steps,
        }


@dataclass
class ToolStatus:
    name: str
    status: str
    detail: str = ""
    level: str = ""
    purpose: str = ""
    impact: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "", [])}


@dataclass
class SearchDimension:
    name: str
    purpose: str
    queries: List[str] = field(default_factory=list)
    required_for_covered: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SearchPlan:
    requirement_id: str
    rule_family: str
    aliases: List[str] = field(default_factory=list)
    dimensions: List[SearchDimension] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "rule_family": self.rule_family,
            "aliases": self.aliases,
            "dimensions": [item.to_dict() for item in self.dimensions],
        }


@dataclass
class SearchTrace:
    requirement_id: str
    dimension: str
    status: str
    queries: List[str] = field(default_factory=list)
    hits: List[Evidence] = field(default_factory=list)
    required_for_covered: bool = True
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "dimension": self.dimension,
            "status": self.status,
            "queries": self.queries,
            "hits": [item.to_dict() for item in self.hits],
            "required_for_covered": self.required_for_covered,
            "note": self.note,
        }


@dataclass
class CoverageRecord:
    requirement: Requirement
    status: str
    confidence: float
    coverage_risk: str
    rule_family: str = "general_behavior"
    evidence_strength: str = "none"
    searched_with: List[str] = field(default_factory=list)
    positive_evidence: List[Evidence] = field(default_factory=list)
    candidate_evidence: List[Dict[str, Any]] = field(default_factory=list)
    issue_ids: List[str] = field(default_factory=list)
    missing_evidence_searches: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    search_plan: Optional[SearchPlan] = None
    search_trace: List[SearchTrace] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement": {
                "id": self.requirement.id,
                "document": self.requirement.document,
                "section": self.requirement.section,
                "quote": self.requirement.quote,
                "normalized": self.requirement.normalized,
                "keywords": self.requirement.keywords,
                "source": self.requirement.source,
            },
            "status": self.status,
            "confidence": round(self.confidence, 3),
            "coverage_risk": self.coverage_risk,
            "rule_family": self.rule_family,
            "evidence_strength": self.evidence_strength,
            "searched_with": self.searched_with,
            "positive_evidence": [item.to_dict() for item in self.positive_evidence],
            "candidate_evidence": self.candidate_evidence,
            "issue_ids": self.issue_ids,
            "missing_evidence_searches": self.missing_evidence_searches,
            "notes": self.notes,
            "search_plan": self.search_plan.to_dict() if self.search_plan else None,
            "search_trace": [item.to_dict() for item in self.search_trace],
        }
