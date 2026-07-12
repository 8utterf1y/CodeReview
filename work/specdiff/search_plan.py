from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from .models import CodeHit, Evidence, Requirement, SearchDimension, SearchPlan, SearchTrace
from .rules.base import RuleFamily


BEHAVIOR_DIMENSIONS = {
    "parser_or_format": "Find parsing, validation, traversal, and encoding behavior.",
    "dispatch_or_routing": "Trace entry, classification, registration, and handler invocation.",
    "state_machine": "Find states, transition conditions, and invalid or terminal handling.",
    "timing_or_randomness": "Find timer, retry, scheduling, jitter, and random APIs on the target path.",
    "config_behavior": "Connect config parsing and defaults to runtime use.",
    "error_handling": "Find detection, propagation, cleanup, rollback, and fallback paths.",
    "security_property": "Find checks that guard the protected action.",
    "observability": "Find event emission on the required execution path.",
    "resource_lifecycle": "Connect acquisition to release and failure cleanup.",
    "compatibility_or_negotiation": "Connect version or capability decisions to runtime behavior.",
    "data_consistency_or_mapping": "Connect source reads to target writes and validation.",
    "module_presence": "Connect build or registration evidence to a reachable handler.",
    "general_behavior": "Find an entry path and observable implementation behavior.",
}


def build_search_plan(requirement: Requirement, family: RuleFamily, terms: Sequence[str]) -> SearchPlan:
    aliases = _aliases(requirement, terms)
    query_terms = aliases[:16]
    return SearchPlan(
        requirement_id=requirement.id,
        rule_family=family.name,
        aliases=aliases,
        dimensions=[
            SearchDimension(
                name="lexical",
                purpose="Find terminology, identifiers, references, and nearby implementation candidates.",
                queries=query_terms,
                required_for_covered=False,
            ),
            SearchDimension(
                name="symbol",
                purpose="Find declarations, registrations, handlers, fields, and protocol or feature symbols.",
                queries=query_terms,
            ),
            SearchDimension(
                name="behavior_path",
                purpose=BEHAVIOR_DIMENSIONS.get(family.name, BEHAVIOR_DIMENSIONS["general_behavior"]),
                queries=query_terms,
            ),
        ],
    )


def build_search_trace(
    plan: SearchPlan,
    text_hits: Sequence[CodeHit],
    symbol_hits: Sequence[CodeHit],
) -> List[SearchTrace]:
    text_evidence = _evidence(text_hits, "lexical search hit")
    symbol_evidence = _evidence(symbol_hits, "symbol-like declaration hit")
    behavior_evidence = [item for item in text_evidence if _looks_executable(item.quote)]
    hit_map = {
        "lexical": text_evidence,
        "symbol": symbol_evidence,
        "behavior_path": behavior_evidence,
    }
    traces: List[SearchTrace] = []
    for dimension in plan.dimensions:
        hits = hit_map.get(dimension.name, [])
        traces.append(
            SearchTrace(
                requirement_id=plan.requirement_id,
                dimension=dimension.name,
                status="completed_with_hits" if hits else "completed_no_hits",
                queries=dimension.queries,
                hits=hits,
                required_for_covered=dimension.required_for_covered,
                note="Search completed; hits are evidence candidates, not proof by themselves.",
            )
        )
    return traces


def completeness_for_covered(traces: Sequence[SearchTrace]) -> Tuple[bool, List[str]]:
    missing = [
        item.dimension
        for item in traces
        if item.required_for_covered and item.status != "completed_with_hits"
    ]
    return (not missing, missing)


def _aliases(requirement: Requirement, terms: Sequence[str]) -> List[str]:
    values = list(terms)
    values.extend(re.findall(r"\b(?:RFC\s*[- ]?\d+|[A-Z][A-Z0-9_]{2,})\b", requirement.quote, re.I))
    seen = set()
    result = []
    for value in values:
        cleaned = str(value).strip()
        key = cleaned.lower().replace(" ", "")
        if len(key) < 3 or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _evidence(hits: Sequence[CodeHit], note: str) -> List[Evidence]:
    return [item.evidence(note) for item in hits]


def _looks_executable(quote: str) -> bool:
    stripped = quote.strip()
    if stripped.startswith(("//", "/*", "*", "#define", "# define", "typedef", "struct", "enum")):
        return False
    return bool(
        re.search(
            r"\b(if|for|while|switch|case|return|throw|catch|dispatch|register|send|recv|handle|"
            r"validate|open|close|free|release|lock|unlock)\b|[A-Za-z_][A-Za-z0-9_]*\s*\(",
            quote,
            re.I,
        )
    )
