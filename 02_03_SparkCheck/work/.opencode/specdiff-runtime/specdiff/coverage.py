from __future__ import annotations

import re
import shutil
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

from .code_index import CodeIndex
from .models import Candidate, CodeHit, CoverageRecord, Evidence, Finding, Requirement, ToolStatus
from .rules.coverage_gate import evaluate_coverage
from .rules.registry import all_rule_families, select_rule_family
from .search_plan import build_search_plan, build_search_trace, completeness_for_covered


def build_coverage_matrix(
    index: CodeIndex,
    requirements: Sequence[Requirement],
    findings: Sequence[Finding],
    candidates: Sequence[Candidate],
    *,
    max_hits_per_requirement: int = 12,
) -> Tuple[List[CoverageRecord], List[ToolStatus]]:
    tool_status = detect_tool_status()
    findings_by_req = _findings_by_requirement(findings)
    candidates_by_req = _candidates_by_requirement(candidates)
    records: List[CoverageRecord] = []

    for req in requirements:
        terms = _search_terms(req)
        positive_hits = _positive_hits(index, terms, max_hits_per_requirement)
        symbol_hits = _symbol_hits(index, terms, max_hits_per_requirement)
        req_findings = findings_by_req.get(_req_key(req), [])
        req_candidates = candidates_by_req.get(req.id, [])
        evidence = _dedupe_evidence([hit.evidence("text search hit") for hit in positive_hits])
        evidence.extend(_dedupe_evidence([hit.evidence("symbol-like declaration hit") for hit in symbol_hits]))
        evidence = _dedupe_evidence(evidence)[:max_hits_per_requirement]

        family = select_rule_family(req)
        search_plan = build_search_plan(req, family, terms)
        search_trace = build_search_trace(search_plan, positive_hits, symbol_hits)
        assessment = evaluate_coverage(req, family, evidence, req_findings, req_candidates)
        complete, missing_dimensions = completeness_for_covered(search_trace)
        if assessment.status == "covered" and not complete:
            assessment.status = "unknown"
            assessment.confidence = min(assessment.confidence, 0.45)
            assessment.coverage_risk = "high"
            assessment.notes.insert(
                0,
                "coverage withheld because required search dimensions lack evidence: "
                + ", ".join(missing_dimensions),
            )
        if req_findings:
            evidence = _dedupe_evidence([item.code_evidence for item in req_findings])[:max_hits_per_requirement]
        records.append(
            CoverageRecord(
                requirement=req,
                status=assessment.status,
                confidence=assessment.confidence,
                coverage_risk=assessment.coverage_risk,
                rule_family=family.name,
                evidence_strength=assessment.strength,
                searched_with=_searched_with(tool_status),
                positive_evidence=evidence,
                candidate_evidence=[_candidate_summary(item) for item in req_candidates[:8]],
                issue_ids=[item.id for item in req_findings],
                missing_evidence_searches=[
                    f"text terms: {', '.join(terms[:10])}" if terms else "no stable search terms extracted",
                    "symbol-like declarations: macros, functions, static globals, enum/case labels",
                ],
                notes=assessment.to_notes(),
                search_plan=search_plan,
                search_trace=search_trace,
            )
        )

    return records, tool_status


def coverage_summary(records: Sequence[CoverageRecord]) -> Dict[str, object]:
    counts = Counter(record.status for record in records)
    family_counts = Counter(record.rule_family for record in records)
    high_risk = [record.requirement.id for record in records if record.coverage_risk == "high"]
    return {
        "requirements_total": len(records),
        "status_counts": dict(sorted(counts.items())),
        "rule_family_counts": dict(sorted(family_counts.items())),
        "high_risk_requirements": high_risk,
    }


def rule_family_stats() -> Dict[str, object]:
    from .rules.base import summarize_families

    return summarize_families(all_rule_families())


def detect_tool_status() -> List[ToolStatus]:
    statuses = [
        ToolStatus(
            "text-index",
            "available",
            "built-in regex search over source files",
            "level1_text_symbol",
            "high-recall candidate discovery",
            "",
        ),
        ToolStatus(
            "symbol-lite",
            "available",
            "built-in symbol-like declaration search",
            "level1_text_symbol",
            "lightweight symbol and declaration discovery",
            "",
        ),
    ]
    optional = {
        "ctags": (
            "level1_text_symbol",
            "symbol index; universal-ctags JSON preferred when available",
            "symbol coverage reduced",
        ),
        "ast-grep": (
            "level2_syntax_ast",
            "AST structural search",
            "structure evidence and rule matching reduced",
        ),
        "tree-sitter": (
            "level2_syntax_ast",
            "Tree-sitter query execution",
            "portable syntax query coverage reduced",
        ),
        "semgrep": (
            "level3_semantic_static",
            "semantic pattern and dataflow rules",
            "rule verification and taint/data-flow coverage reduced",
        ),
        "codeql": (
            "level3_semantic_static",
            "database-backed semantic/code-flow queries",
            "compiled-language semantic coverage reduced",
        ),
        "joern": (
            "level3_semantic_static",
            "CPG-based control/data-flow queries for C/C++ and JVM code",
            "CPG call/control/data-flow coverage reduced",
        ),
        "test-runner": (
            "level4_dynamic_validation",
            "unit/contract/property/fuzz test validation hook",
            "dynamic behavior validation unavailable by default",
        ),
    }
    for name, (level, detail, impact) in optional.items():
        path = shutil.which(name)
        statuses.append(
            ToolStatus(
                name=name,
                status="available" if path else "unavailable",
                detail=path or detail,
                level=level,
                purpose=detail,
                impact="" if path else impact,
            )
        )
    return statuses


def _findings_by_requirement(findings: Sequence[Finding]) -> Dict[Tuple[str, str, str], List[Finding]]:
    result: Dict[Tuple[str, str, str], List[Finding]] = defaultdict(list)
    for finding in findings:
        result[
            (
                finding.spec_evidence.document or "",
                finding.spec_evidence.section or "",
                finding.spec_evidence.quote,
            )
        ].append(finding)
    return result


def _candidates_by_requirement(candidates: Sequence[Candidate]) -> Dict[str, List[Candidate]]:
    result: Dict[str, List[Candidate]] = defaultdict(list)
    for candidate in candidates:
        result[candidate.requirement.id].append(candidate)
    return result


def _req_key(req: Requirement) -> Tuple[str, str, str]:
    return (req.document, req.section, req.quote)


def _search_terms(req: Requirement) -> List[str]:
    words = list(req.keywords)
    words.extend(re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}", req.normalized))
    words.extend(re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", req.quote))
    stop = {
        "the",
        "and",
        "that",
        "with",
        "must",
        "should",
        "shall",
        "required",
        "without",
        "implementation",
        "process",
        "valid",
        "support",
        "https",
        "http",
        "www",
        "org",
        "com",
        "rfc",
        "editor",
        "rfc-editor",
        "violates",
        "violate",
        "section",
        "unknown",
        "summary",
        "issue",
        "issues",
    }
    result = []
    seen = set()
    for word in words:
        cleaned = word.strip("_-").lower()
        if len(cleaned) < 3 or cleaned in stop or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result[:16]


def _positive_hits(index: CodeIndex, terms: Sequence[str], limit: int) -> List[CodeHit]:
    if not terms:
        return []
    strong_terms = [term for term in terms if len(term) >= 6 or re.search(r"\d|_", term)]
    hits: List[CodeHit] = []
    for path in index.files:
        rel = index.rel(path)
        try:
            lines = index.read(path).splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, 1):
            lowered = line.lower()
            if _low_signal_line(lowered):
                continue
            matched = [term for term in terms[:16] if term in lowered]
            strong_matched = [term for term in strong_terms[:12] if term in lowered]
            if len(matched) >= 2 or strong_matched:
                hits.append(CodeHit(file=rel, line=idx, quote=line.strip()[:500]))
                if len(hits) >= limit:
                    return hits
    return hits


def _symbol_hits(index: CodeIndex, terms: Sequence[str], limit: int) -> List[CodeHit]:
    if not terms:
        return []
    symbol_terms = [term for term in terms if len(term) >= 5 or re.search(r"\d|_", term)]
    if not symbol_terms:
        return []
    term_pattern = "|".join(re.escape(term) for term in symbol_terms[:10])
    pattern = (
        r"^\s*(#\s*define\s+|typedef\s+|enum\s+|struct\s+|case\s+|"
        r"(static\s+)?(inline\s+)?[A-Za-z_][A-Za-z0-9_\s\*]*\s+)"
        r"[A-Za-z_][A-Za-z0-9_]*(" + term_pattern + r")[A-Za-z0-9_]*\b"
    )
    return [hit for hit in index.search(pattern, max_hits=limit) if not _low_signal_line(hit.quote.lower())]


def _candidate_summary(candidate: Candidate) -> Dict[str, object]:
    return {
        "id": candidate.id,
        "scanner": candidate.scanner,
        "category": candidate.category,
        "title": candidate.title,
        "confidence": round(candidate.confidence, 3),
        "evidence": candidate.evidence.to_dict(),
        "rationale": candidate.rationale,
        "next_steps": candidate.next_steps,
    }


def _searched_with(tool_status: Iterable[ToolStatus]) -> List[str]:
    return [tool.name for tool in tool_status if tool.status == "available"]


def _dedupe_evidence(items: Sequence[Evidence]) -> List[Evidence]:
    seen = set()
    result: List[Evidence] = []
    for item in items:
        key = (item.file, item.line, item.quote)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _low_signal_line(line: str) -> bool:
    low_signal = [
        "copyright",
        "redistribution",
        "all rights reserved",
        "this list of conditions",
        "without modification",
        "from rfc 2553",
        "wrote this file",
        "such damage",
        "loss of use",
        "following disclaimer",
    ]
    return any(marker in line for marker in low_signal)
