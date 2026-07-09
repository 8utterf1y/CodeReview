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
