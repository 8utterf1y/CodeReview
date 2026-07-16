from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


NORMATIVE_RE = re.compile(
    r"\b(MUST(?:\s+NOT)?|SHALL(?:\s+NOT)?|SHOULD(?:\s+NOT)?|REQUIRED|MAY|OPTIONAL)\b",
    re.I,
)
BEHAVIOR_RE = re.compile(
    r"\b(send|receive|process|validate|discard|forward|respond|delay|retransmit|"
    r"parse|encode|decode|select|generate|ignore|drop|accept|reject|support|implement)\b",
    re.I,
)
SECTION_REF_RE = re.compile(r"\bsection\s+(\d+(?:\.\d+)*)\b|[Ss]ee\s+(\d+(?:\.\d+)*)")
DEFINITION_RE = re.compile(r"\b(?:is defined as|means|refers to|is called|is termed)\b", re.I)
BOILERPLATE_SECTIONS = {"authors", "acknowledgements", "acknowledgments", "references", "copyright"}


def build_requirement_pack_artifact(
    *,
    inventory: str,
    references: List[Tuple[str, str]],
    documents: List[Dict[str, Any]],
    excluded_references: List[Dict[str, str]],
    soft_max_clauses: int = 12,
    hard_max_clauses: int = 25,
) -> Dict[str, Any]:
    scope = effective_rfc_scope(references, documents, excluded_references)
    clauses = [clause for document in documents for clause in document["clauses"]]
    relations = build_relations(clauses)
    packs, dispositions = build_requirement_packs(
        references=references,
        clauses=clauses,
        relations=relations,
        scope=scope,
        soft_max_clauses=soft_max_clauses,
        hard_max_clauses=hard_max_clauses,
    )
    return {
        "schema_version": "1.0",
        "artifact_type": "rfc_corpus",
        "inventory": inventory,
        "sources": [
            {key: value for key, value in document.items() if key != "clauses"}
            for document in documents
        ],
        "scope": scope,
        "clauses": clauses,
        "relations": relations,
        "dispositions": dispositions,
        "requirement_packs": packs,
        "excluded_references": excluded_references,
        "coverage": {
            "corpus_total": len(clauses),
            "packs_total": len(packs),
            "disposition_counts": _counts(item["disposition"] for item in dispositions),
            "unclassified": sum(1 for item in dispositions if item["disposition"] == "unclassified"),
        },
        "limitations": [
            "RFC clauses are corpus records. Requirement Packs are bounded audit topics, not final findings.",
            "Pack construction uses document structure and RFC metadata only; implementation status is decided later.",
        ],
    }


def effective_rfc_scope(
    references: List[Tuple[str, str]],
    documents: List[Dict[str, Any]],
    excluded_references: List[Dict[str, str]],
) -> Dict[str, Dict[str, Any]]:
    referenced = {number for number, _title in references}
    excluded = {item["rfc"] for item in excluded_references}
    by_number = {document["rfc"]: document for document in documents}
    obsoleted_by: Dict[str, List[str]] = defaultdict(list)
    for document in documents:
        for old in document.get("obsoletes", []):
            if old in referenced:
                obsoleted_by[old].append(document["rfc"])

    scope: Dict[str, Dict[str, Any]] = {}
    for number, title in references:
        if number in excluded:
            scope[f"RFC{number}"] = {
                "rfc": number,
                "title": title,
                "scope_status": "meta_spec",
                "reason": "reference defines vocabulary or terminology, not product behavior",
            }
        elif obsoleted_by.get(number):
            scope[f"RFC{number}"] = {
                "rfc": number,
                "title": title,
                "scope_status": "historical_context",
                "obsoleted_by": [f"RFC{item}" for item in sorted(obsoleted_by[number])],
                "reason": "obsoleted by another RFC in the same manifest",
            }
        elif by_number.get(number, {}).get("updates"):
            scope[f"RFC{number}"] = {
                "rfc": number,
                "title": title,
                "scope_status": "overlay",
                "updates": [f"RFC{item}" for item in sorted(by_number[number].get("updates", []))],
                "reason": "updates another RFC and should be treated as overlay context",
            }
        else:
            scope[f"RFC{number}"] = {
                "rfc": number,
                "title": title,
                "scope_status": "effective",
                "reason": "active implementation-bearing reference in manifest",
            }
    return scope


def build_relations(clauses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_doc_section: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for clause in clauses:
        by_doc_section[(clause["document_id"], clause["section"])].append(clause)
        by_doc[clause["document_id"]].append(clause)

    relations: List[Dict[str, Any]] = []
    for clause in clauses:
        doc_id = clause["document_id"]
        text = clause["text"]
        for match in SECTION_REF_RE.finditer(text):
            target_section = match.group(1) or match.group(2)
            for target in by_doc_section.get((doc_id, target_section), [])[:3]:
                if target["id"] != clause["id"]:
                    relations.append(_relation(clause["id"], target["id"], "REFERENCES_SECTION", "section_reference_parser", 1.0))
        parent = _parent_section(clause["section"])
        if parent:
            candidates = by_doc_section.get((doc_id, parent), [])
            if candidates:
                relations.append(_relation(clause["id"], candidates[0]["id"], "PARENT_CONTEXT", "section_hierarchy", 0.75))
        if clause["paragraph_index"] > 1:
            prev_id = f"{doc_id}:{clause['section']}:p{clause['paragraph_index'] - 1:04d}"
            if any(item["id"] == prev_id for item in by_doc[doc_id]):
                relations.append(_relation(clause["id"], prev_id, "PRECEDING_CONTEXT", "paragraph_order", 0.65))
        if DEFINITION_RE.search(text):
            continue
        for definition in _definition_candidates(by_doc[doc_id]):
            if definition["id"] != clause["id"] and _shares_term(clause["text"], definition["text"]):
                relations.append(_relation(clause["id"], definition["id"], "DEFINED_IN", "definition_phrase_match", 0.55))
    return _dedupe_relations(relations)


def build_requirement_packs(
    *,
    references: List[Tuple[str, str]],
    clauses: List[Dict[str, Any]],
    relations: List[Dict[str, Any]],
    scope: Dict[str, Dict[str, Any]],
    soft_max_clauses: int,
    hard_max_clauses: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    relation_by_source: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for relation in relations:
        relation_by_source[relation["source_clause_id"]].append(relation)

    clause_by_id = {clause["id"]: clause for clause in clauses}
    packs: List[Dict[str, Any]] = []
    disposition: Dict[str, Dict[str, Any]] = {}

    for clause in sorted(clauses, key=lambda item: item["id"]):
        doc_scope = scope.get(clause["document_id"], {})
        if doc_scope.get("scope_status") in {"historical_context", "meta_spec"}:
            disposition[clause["id"]] = _disposition(clause["id"], doc_scope["scope_status"], [], "RFC_SCOPE")
            continue
        if not _is_seed_clause(clause):
            disposition[clause["id"]] = _disposition(clause["id"], _non_seed_disposition(clause), [], "NON_SEED_CONTEXT")
            continue
        member_ids, relation_ids = _expand_seed(clause, clause_by_id, relation_by_source, soft_max_clauses, hard_max_clauses)
        pack = _pack_from_members(clause, member_ids, relation_ids, clause_by_id, hard_max_clauses)
        packs.append(pack)
        for member_id in member_ids:
            current = disposition.get(member_id)
            if current and current["disposition"] == "pack_seed":
                continue
            disposition[member_id] = _disposition(
                member_id,
                "pack_seed" if member_id == clause["id"] else "pack_context",
                [pack["id"]],
                "BCP14_BEHAVIOR" if member_id == clause["id"] else "DOCUMENT_CONTEXT",
            )

    for number, title in references:
        doc_id = f"RFC{number}"
        doc_scope = scope.get(doc_id, {})
        if doc_scope.get("scope_status") not in {"effective", "overlay"}:
            continue
        doc_clauses = [clause for clause in clauses if clause["document_id"] == doc_id]
        if not doc_clauses or not any(_is_seed_clause(clause) for clause in doc_clauses):
            continue
        pack = _capability_pack(number, title)
        packs.append(pack)

    for clause in clauses:
        disposition.setdefault(clause["id"], _disposition(clause["id"], "unclassified", [], "NO_CLASSIFIER_MATCH"))

    packs = sorted(_dedupe_packs(packs), key=lambda item: item["id"])
    return packs, [disposition[key] for key in sorted(disposition)]


def _is_seed_clause(clause: Dict[str, Any]) -> bool:
    if clause.get("section_kind") in {"references_section", "administrative", "example"}:
        return False
    text = clause["text"]
    return bool(NORMATIVE_RE.search(text) and BEHAVIOR_RE.search(text))


def _non_seed_disposition(clause: Dict[str, Any]) -> str:
    section_kind = clause.get("section_kind")
    if section_kind in {"references_section", "administrative", "example"}:
        return section_kind
    if DEFINITION_RE.search(clause["text"]):
        return "definition_context"
    if NORMATIVE_RE.search(clause["text"]):
        return "informational"
    return "informational"


def _expand_seed(
    seed: Dict[str, Any],
    clause_by_id: Dict[str, Dict[str, Any]],
    relation_by_source: Dict[str, List[Dict[str, Any]]],
    soft_max: int,
    hard_max: int,
) -> Tuple[List[str], List[str]]:
    members = [seed["id"]]
    relation_ids: List[str] = []
    priorities = {"REFERENCES_SECTION": 0, "DEFINED_IN": 1, "PARENT_CONTEXT": 2, "PRECEDING_CONTEXT": 3}
    for relation in sorted(relation_by_source.get(seed["id"], []), key=lambda item: (priorities.get(item["type"], 9), item["id"])):
        if len(members) >= hard_max:
            break
        if relation["target_clause_id"] not in clause_by_id:
            continue
        if len(members) >= soft_max and relation["type"] not in {"REFERENCES_SECTION", "DEFINED_IN"}:
            continue
        members.append(relation["target_clause_id"])
        relation_ids.append(relation["id"])
    return sorted(set(members)), sorted(set(relation_ids))


def _pack_from_members(
    seed: Dict[str, Any],
    member_ids: List[str],
    relation_ids: List[str],
    clause_by_id: Dict[str, Dict[str, Any]],
    hard_max: int,
) -> Dict[str, Any]:
    clauses = [clause_by_id[item] for item in member_ids]
    levels = sorted({level for clause in clauses for level in clause.get("normative_levels", [])})
    sections = sorted({clause["section"] for clause in clauses})
    pack_id = _stable_pack_id(seed["document_id"], [seed["id"]], member_ids, relation_ids)
    return {
        "id": pack_id,
        "pack_type": "requirement_behavior",
        "seed_clause_ids": [seed["id"]],
        "clause_ids": member_ids,
        "relation_ids": relation_ids,
        "document_ids": sorted({clause["document_id"] for clause in clauses}),
        "sections": sections,
        "normative_levels": levels,
        "normative_strength": _normative_strength(levels),
        "candidate_kind": "behavior",
        "status": "oversized" if len(member_ids) > hard_max else "ready",
        "document": seed["document"],
        "section": seed["section"],
        "quote": seed["text"][:1200],
        "normalized": _normalize_text(seed["text"]),
        "keywords": _keywords(" ".join(clause["text"] for clause in clauses)),
        "clauses": clauses,
    }


def _capability_pack(number: str, title: str) -> Dict[str, Any]:
    doc_id = f"RFC{number}"
    name = _capability_name(number, title)
    pack_id = f"PACK-{doc_id}-CAPABILITY-{_hash([doc_id, name])}"
    text = f"{doc_id} capability presence: {name}"
    return {
        "id": pack_id,
        "pack_type": "capability_presence",
        "seed_clause_ids": [],
        "clause_ids": [],
        "relation_ids": [],
        "document_ids": [doc_id],
        "sections": ["manifest"],
        "normative_levels": [],
        "normative_strength": "capability",
        "candidate_kind": "capability_presence",
        "status": "ready",
        "document": f"RFC {number}",
        "section": "manifest",
        "quote": text,
        "normalized": f"Investigate whether the repository implements the capability represented by {doc_id}: {name}.",
        "keywords": _keywords(f"{title} {name} rfc{number}"),
        "capability": name,
        "scope_source": {"type": "rfc_manifest", "document": f"RFC {number}", "title": title},
        "responsibility_status": "unresolved",
        "clauses": [],
    }


def _capability_name(number: str, title: str) -> str:
    title = re.sub(r"\[[^]]+\]\([^)]*\)", "", title)
    title = re.sub(r"\bRFC\s*\d+\b", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -") or f"RFC {number}"


def _stable_pack_id(doc_id: str, seed_ids: List[str], member_ids: List[str], relation_ids: List[str]) -> str:
    return f"PACK-{doc_id}-{_hash([doc_id, *sorted(seed_ids), *sorted(member_ids), *sorted(relation_ids)])}"


def _hash(parts: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:10].upper()


def _relation(source: str, target: str, kind: str, source_method: str, confidence: float) -> Dict[str, Any]:
    relation_id = f"REL-{_hash([source, target, kind, source_method])}"
    return {
        "id": relation_id,
        "source_clause_id": source,
        "target_clause_id": target,
        "type": kind,
        "source": source_method,
        "confidence": confidence,
    }


def _disposition(clause_id: str, disposition: str, pack_ids: List[str], reason_code: str) -> Dict[str, Any]:
    return {"clause_id": clause_id, "disposition": disposition, "pack_ids": pack_ids, "reason_code": reason_code}


def _parent_section(section: str) -> Optional[str]:
    if "." not in section:
        return None
    return section.rsplit(".", 1)[0]


def _definition_candidates(clauses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [clause for clause in clauses if DEFINITION_RE.search(clause["text"])]


def _shares_term(left: str, right: str) -> bool:
    left_terms = set(_keywords(left))
    right_terms = set(_keywords(right))
    return bool(left_terms & right_terms)


def _dedupe_relations(relations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    rows = []
    for relation in sorted(relations, key=lambda item: item["id"]):
        if relation["id"] in seen:
            continue
        seen.add(relation["id"])
        rows.append(relation)
    return rows


def _dedupe_packs(packs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {}
    for pack in packs:
        by_id.setdefault(pack["id"], pack)
    return list(by_id.values())


def _normative_strength(levels: List[str]) -> str:
    upper = {level.upper() for level in levels}
    if upper & {"MUST", "MUST NOT", "SHALL", "SHALL NOT", "REQUIRED"}:
        return "required"
    if upper & {"SHOULD", "SHOULD NOT"}:
        return "recommended"
    if upper & {"MAY", "OPTIONAL"}:
        return "optional"
    return "context"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:1200]


def _keywords(text: str) -> List[str]:
    stop = {
        "the", "and", "that", "with", "shall", "must", "should", "not", "for", "from",
        "this", "there", "their", "when", "where", "which", "will", "may", "are", "can",
    }
    return sorted({word for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()) if word not in stop})[:24]


def _counts(values: Iterable[str]) -> Dict[str, int]:
    rows: Dict[str, int] = {}
    for value in values:
        rows[value] = rows.get(value, 0) + 1
    return dict(sorted(rows.items()))
