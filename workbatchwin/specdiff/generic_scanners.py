from __future__ import annotations

import re
from typing import Any, Iterable, List, Tuple

from .code_index import CodeIndex
from .models import Candidate, CodeHit, Evidence, Finding, Requirement


def run_generic_scanners(index: CodeIndex, requirements: List[Requirement]) -> Tuple[List[Candidate], List[Finding]]:
    candidates: List[Candidate] = []
    for scanner in SCANNERS:
        candidates.extend(scanner(index, requirements))
    candidates = _renumber_candidates(_dedupe_candidates(candidates))
    findings = _promote_candidates(candidates)
    return candidates, findings


def scan_hard_limits(index: CodeIndex, requirements: List[Requirement]) -> List[Candidate]:
    relevant = [
        req
        for req in requirements
        if _has_any(req, ["all", "each", "every", "valid", "option", "prefix", "limit", "maximum"])
    ]
    if not relevant:
        return []

    hits = index.search(
        r"\b(max|limit|cap|count|num|nr|threshold)[A-Za-z0-9_]*\b.*=\s*(?:[1-9]|[1-9][0-9])\b|"
        r"\bif\s*\([^)]*(?:>|>=)\s*[A-Za-z0-9_]*(?:max|limit|cap)",
        max_hits=80,
    )
    return [
        _candidate(
            scanner="HardLimitScanner",
            category="constant_or_limit",
            title="Possible hardcoded limit weaker than specification",
            req=_best_req(relevant, hit.quote),
            hit=hit,
            confidence=0.58,
            rationale="A requirement suggests processing all/every valid item, while code has a small cap or limit guard.",
            next_steps=[
                "Inspect whether the limit applies to spec-covered valid inputs.",
                "Check whether the limit is configurable and whether dropped input is reported as failure.",
            ],
        )
        for hit in hits
        if not _is_low_signal_file(hit.file)
    ][:20]


def scan_timing_randomness(index: CodeIndex, requirements: List[Requirement]) -> List[Candidate]:
    relevant = [
        req
        for req in requirements
        if _has_any(req, ["delay", "random", "jitter", "backoff", "timeout", "timer", "retry"])
    ]
    if not relevant:
        return []

    send_hits = index.search(r"\b(send|output|emit|notify|advert|reply|respond|transmit)\b", max_hits=120)
    candidates: List[Candidate] = []
    for hit in send_hits:
        if _is_low_signal_file(hit.file):
            continue
        if _quote_has_any(hit.quote, ["delay", "random", "timer", "timeout", "callout", "sleep"]):
            continue
        candidates.append(
            _candidate(
                scanner="TimingRandomnessScanner",
                category="timing_or_randomness",
                title="Possible immediate send path for requirement involving timing/randomness",
                req=_best_req(relevant, hit.quote),
                hit=hit,
                confidence=0.5,
                rationale="Spec mentions timing/randomness but candidate send path does not show delay/randomization on the evidence line.",
                next_steps=[
                    "Read the enclosing function and nearby callers.",
                    "Search nearby code for random/timer APIs before promoting this candidate.",
                ],
            )
        )
    return candidates[:25]


def scan_chain_traversal(index: CodeIndex, requirements: List[Requirement]) -> List[Candidate]:
    relevant = [
        req
        for req in requirements
        if _has_any(req, ["chain", "list", "sequence", "extension", "header", "walk", "traverse", "for each"])
    ]
    if not relevant:
        return []

    hits = index.search(
        r"only (checks|looks|reads)|doesn.t follow|first [A-Za-z0-9_ -]*(header|item|entry)|"
        r"\bif\s*\([^)]*(next|proto|type|kind)[^)]*==",
        max_hits=80,
    )
    candidates: List[Candidate] = []
    for hit in hits:
        if _is_low_signal_file(hit.file):
            continue
        confidence = 0.72 if _quote_has_any(hit.quote, ["only", "doesn", "first"]) else 0.52
        candidates.append(
            _candidate(
                scanner="ChainTraversalScanner",
                category="parser_or_format",
                title="Possible incomplete traversal of a required chain/list",
                req=_best_req(relevant, hit.quote),
                hit=hit,
                confidence=confidence,
                rationale="Spec appears to require chain/list traversal; code evidence suggests a single-step or first-element check.",
                next_steps=[
                    "Inspect whether code loops through the entire chain/list.",
                    "Check malformed/edge-case handling for intermediate elements.",
                ],
            )
        )
    return candidates[:25]


def scan_missing_module_surface(index: CodeIndex, requirements: List[Requirement]) -> List[Candidate]:
    candidates: List[Candidate] = []
    module_reqs = [
        req
        for req in requirements
        if _has_any(req, ["support", "protocol", "client", "server", "module", "service", "configuration"])
    ]
    for req in module_reqs:
        terms = [term for term in _keyword_strings(req) if len(term) >= 5][:6]
        if not terms:
            continue
        hits = index.contains_any(terms)
        code_hits = [hit for hit in hits if not _is_low_signal_file(hit.file)]
        if code_hits:
            continue
        candidates.append(
            Candidate(
                id="CANDIDATE",
                scanner="MissingModuleScanner",
                category="module_presence",
                title=f"Possible missing implementation surface for requirement {req.id}",
                confidence=0.48,
                requirement=req,
                evidence=Evidence(file="repository scan", line=0, quote=f"No implementation hits for terms: {', '.join(terms)}"),
                rationale="Spec indicates a module/protocol/capability, but repository search did not find implementation-like symbols.",
                next_steps=[
                    "Search build files and configuration knobs.",
                    "Exclude documentation/vendor-only hits before promoting.",
                ],
            )
        )
    return candidates[:20]


def scan_dispatch_order(index: CodeIndex, requirements: List[Requirement]) -> List[Candidate]:
    relevant = [
        req
        for req in requirements
        if _has_any(req, ["dispatch", "route", "handler", "message", "type", "multicast", "filter", "packet"])
    ]
    if not relevant:
        return []

    hits = index.search(r"\breturn\s+FILTER_|handler|dispatch|route|switch\s*\(|case\s+[A-Za-z0-9_]+", max_hits=120)
    candidates = []
    for hit in hits:
        if _is_low_signal_file(hit.file):
            continue
        candidates.append(
            _candidate(
                scanner="DispatchOrderScanner",
                category="dispatch_or_routing",
                title="Possible dispatch/filter ordering issue",
                req=_best_req(relevant, hit.quote),
                hit=hit,
                confidence=0.46,
                rationale="Spec involves message routing/dispatch; code evidence is a candidate filter or handler decision point.",
                next_steps=[
                    "Inspect ordering of earlier returns and more-specific handlers.",
                    "Check whether protocol-specific messages can be intercepted by a generic path.",
                ],
            )
        )
    return candidates[:25]


SCANNERS = [
    scan_hard_limits,
    scan_timing_randomness,
    scan_chain_traversal,
    scan_missing_module_surface,
    scan_dispatch_order,
]


def _candidate(
    *,
    scanner: str,
    category: str,
    title: str,
    req: Requirement,
    hit: CodeHit,
    confidence: float,
    rationale: str,
    next_steps: List[str],
) -> Candidate:
    return Candidate(
        id="CANDIDATE",
        scanner=scanner,
        category=category,
        title=title,
        confidence=confidence,
        requirement=req,
        evidence=hit.evidence("Generic scanner candidate; requires alignment judgment before final reporting."),
        rationale=rationale,
        next_steps=next_steps,
    )


def _promote_candidates(candidates: List[Candidate]) -> List[Finding]:
    findings: List[Finding] = []
    for candidate in candidates:
        if candidate.confidence < 0.72:
            continue
        findings.append(
            Finding(
                id="ISSUE",
                title=candidate.title,
                match_type="partial_match",
                severity="MEDIUM",
                confidence=candidate.confidence,
                description=candidate.rationale,
                spec_evidence=candidate.requirement.evidence(),
                code_evidence=candidate.evidence,
                verification=[
                    f"Raised by {candidate.scanner}.",
                    *candidate.next_steps,
                ],
            )
        )
    return _renumber_findings(findings)


def _best_req(requirements: List[Requirement], quote: str) -> Requirement:
    quote_l = quote.lower()
    scored = []
    for req in requirements:
        score = sum(1 for kw in _keyword_strings(req) if kw.lower() in quote_l)
        scored.append((score, req))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _has_any(req: Requirement, terms: List[str]) -> bool:
    blob = " ".join([req.normalized, req.quote, " ".join(_keyword_strings(req))]).lower()
    return any(term.lower() in blob for term in terms)


def _quote_has_any(quote: str, terms: List[str]) -> bool:
    lower = quote.lower()
    return any(term.lower() in lower for term in terms)


def _is_low_signal_file(path: str) -> bool:
    return bool(
        re.search(
            r"(^|/)(doc|docs|test|tests|examples?|contrib|vendor|third_party|tools|app|adapter)/"
            r"|(^|/)dpdk/(drivers|examples|doc|dts)/"
            r"|readme|license|changelog",
            path,
            re.I,
        )
    )


def _dedupe_candidates(candidates: List[Candidate]) -> List[Candidate]:
    seen = set()
    result: List[Candidate] = []
    for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
        key = (candidate.scanner, candidate.requirement.id, candidate.evidence.file, candidate.evidence.line, candidate.evidence.quote)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _renumber_candidates(candidates: List[Candidate]) -> List[Candidate]:
    for idx, candidate in enumerate(candidates, 1):
        candidate.id = f"CANDIDATE-{idx:04d}"
    return candidates


def _renumber_findings(findings: List[Finding]) -> List[Finding]:
    for idx, finding in enumerate(findings, 1):
        finding.id = f"GENERIC-{idx:03d}"
    return findings


def _keyword_strings(req: Requirement) -> List[str]:
    return _flatten_strings(req.keywords)


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
