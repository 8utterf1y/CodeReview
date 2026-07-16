from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .rfc_packs import build_requirement_pack_artifact


RFC_PATTERN = re.compile(r"\bRFC\s*(\d{3,5})\b", re.I)
SECTION_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)*)\.\s{2,}(.+?)\s*$")
NORMATIVE_PATTERN = re.compile(r"\b(?:MUST(?:\s+NOT)?|SHOULD(?:\s+NOT)?|MAY|REQUIRED|SHALL(?:\s+NOT)?)\b", re.I)
RFC_FETCH_TIMEOUTS = (30, 60)
RFC_FETCH_URLS = (
    "https://www.rfc-editor.org/rfc/rfc{number}.txt",
    "https://www.ietf.org/rfc/rfc{number}.txt",
)


def prepare_rfc_requirements(
    inventory: Path, cache_dir: Path, *, max_per_rfc: Optional[int] = None, offline: bool = False
) -> Dict[str, Any]:
    references = extract_rfc_references(inventory)
    documents: List[Dict[str, Any]] = []
    excluded: List[Dict[str, str]] = []
<<<<<<< HEAD
    unresolved: List[Dict[str, str]] = []
=======
>>>>>>> bc85301 (workbatchwin)
    for number, title in references:
        if _is_vocabulary_reference(title):
            excluded.append({"rfc": number, "title": title, "reason": "normative vocabulary, not implementation behavior"})
            continue
<<<<<<< HEAD
        try:
            text, source = load_rfc_text(number, cache_dir, offline=offline)
        except (FileNotFoundError, TimeoutError, OSError) as exc:
            unresolved.append({"rfc": number, "title": title, "reason": str(exc)})
            continue
=======
        text, source = load_rfc_text(number, cache_dir, offline=offline)
>>>>>>> bc85301 (workbatchwin)
        clauses = extract_rfc_corpus_clauses(number, title, text, max_per_rfc=max_per_rfc)
        metadata = extract_rfc_metadata(number, text)
        documents.append({
            "document_id": f"RFC{number}", "rfc": number, "title": title, **source, **metadata,
            "clauses_emitted": len(clauses), "clauses": clauses,
        })
<<<<<<< HEAD
    if not documents and unresolved:
        detail = "; ".join(f"RFC {item['rfc']}: {item['reason']}" for item in unresolved[:5])
        raise TimeoutError(f"all RFC fetches failed or were unavailable: {detail}")
    artifact = build_requirement_pack_artifact(
=======
    return build_requirement_pack_artifact(
>>>>>>> bc85301 (workbatchwin)
        inventory=str(inventory.resolve()),
        references=references,
        documents=documents,
        excluded_references=excluded,
    )
<<<<<<< HEAD
    artifact["unresolved_references"] = unresolved
    return artifact
=======
>>>>>>> bc85301 (workbatchwin)


def extract_rfc_references(path: Path) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    seen = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = RFC_PATTERN.search(line)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        title = cells[1] if len(cells) > 1 else f"RFC {number}"
        title = re.sub(r"\[[^]]+\]\([^)]*\)", "", title).strip() or f"RFC {number}"
        rows.append((number, title))
    return rows


def load_rfc_text(number: str, cache_dir: Path, *, offline: bool) -> Tuple[str, Dict[str, str]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"rfc{number}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace"), {"source_url": f"https://www.rfc-editor.org/rfc/rfc{number}.txt", "cache": str(path), "retrieval": "cache"}
    if offline:
        raise FileNotFoundError(f"RFC {number} is not cached and offline mode is enabled")
    text, url = _fetch_rfc_text(number)
    path.write_text(text, encoding="utf-8")
    return text, {"source_url": url, "cache": str(path), "retrieval": "network"}


def _fetch_rfc_text(number: str) -> Tuple[str, str]:
    errors: List[str] = []
    for url_template in RFC_FETCH_URLS:
        url = url_template.format(number=number)
        for timeout in RFC_FETCH_TIMEOUTS:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "SpecDiff/1.0 (RFC obligation compiler)"})
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    text = response.read().decode("utf-8", errors="replace")
                if text.strip():
                    return text, url
                errors.append(f"{url} timeout={timeout}: empty response")
            except (TimeoutError, socket.timeout) as exc:
                errors.append(f"{url} timeout={timeout}: {exc}")
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                errors.append(f"{url} timeout={timeout}: {reason}")
            except OSError as exc:
                errors.append(f"{url} timeout={timeout}: {exc}")
            time.sleep(0.2)
    detail = "; ".join(errors[:8])
    raise TimeoutError(f"RFC {number} fetch failed after retries. Tried mirrors: {detail}")


def extract_normative_clauses(number: str, title: str, text: str, *, max_per_rfc: Optional[int]) -> List[Dict[str, Any]]:
    return [
        _clause_to_requirement(clause)
        for clause in extract_rfc_corpus_clauses(number, title, text, max_per_rfc=max_per_rfc)
        if NORMATIVE_PATTERN.search(clause["text"]) and not _is_non_behavior_section(clause["section"])
    ]


def extract_rfc_corpus_clauses(number: str, title: str, text: str, *, max_per_rfc: Optional[int]) -> List[Dict[str, Any]]:
    section = "unknown"
    paragraphs: List[Tuple[str, str]] = []
    lines: List[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        section_match = SECTION_PATTERN.match(line)
        if section_match:
            _append_paragraph(paragraphs, section, lines)
            section = section_match.group(1)
            lines = []
            continue
        if not line.strip():
            _append_paragraph(paragraphs, section, lines)
            lines = []
            continue
        if _is_layout_line(line):
            continue
        lines.append(line.strip())
    _append_paragraph(paragraphs, section, lines)

    clauses = []
    per_section_counter: Dict[str, int] = {}
    for index, (section_id, paragraph) in enumerate(paragraphs, 1):
        per_section_counter[section_id] = per_section_counter.get(section_id, 0) + 1
        paragraph_index = per_section_counter[section_id]
        clause = {
            "id": f"RFC{number}:{section_id}:p{paragraph_index:04d}",
            "document_id": f"RFC{number}",
            "document": f"RFC {number}",
            "section": section_id,
            "paragraph_index": paragraph_index,
            "text": paragraph[:1600],
            "quote": paragraph[:1200],
            "normalized": paragraph[:1200],
            "keywords": _keywords(paragraph),
            "normative_levels": _normative_levels(paragraph),
            "section_kind": _section_kind(section_id, paragraph),
            "source": "rfc_corpus_clause",
        }
        clauses.append(clause)
        if max_per_rfc is not None and len(clauses) >= max_per_rfc:
            break
    return clauses


def extract_rfc_metadata(number: str, text: str) -> Dict[str, Any]:
    header = "\n".join(text.splitlines()[:80])
    return {
        "obsoletes": _header_numbers(header, "Obsoletes"),
        "obsoleted_by": _header_numbers(header, "Obsoleted by"),
        "updates": _header_numbers(header, "Updates"),
        "updated_by": _header_numbers(header, "Updated by"),
    }


def _clause_to_requirement(clause: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": clause["id"].replace(":", "-"),
        "document": clause["document"],
        "section": clause["section"],
        "quote": clause["quote"],
        "normalized": clause["normalized"],
        "keywords": clause["keywords"],
        "source": "rfc_normative_clause",
        "applicability": "unconfirmed",
    }


def _append_paragraph(target: List[Tuple[str, str]], section: str, lines: List[str]) -> None:
    paragraph = " ".join(lines).strip()
    if paragraph:
        target.append((section, paragraph))


def _is_layout_line(line: str) -> bool:
    return bool(
        line.startswith("\f")
        or re.match(r"^RFC\s+\d+\s+", line)
        or re.match(r"^\S.+\[Page\s+\d+\]$", line)
        or re.match(r"^\s*\d+\s*$", line)
    )


def _is_non_behavior_section(section: str) -> bool:
    return section in {"1", "2", "2.1", "2.2", "2.3", "14", "14.1", "14.2"}


def _section_kind(section: str, paragraph: str) -> str:
    lower = paragraph.lower()
    if "references" in lower and section in {"9", "10", "11", "12", "13", "14", "15"}:
        return "references_section"
    if any(word in lower for word in ("copyright", "author's address", "authors' addresses", "acknowledg")):
        return "administrative"
    if lower.startswith("example") or " for example" in lower:
        return "example"
    return "body"


def _is_vocabulary_reference(title: str) -> bool:
    return bool(re.search(r"key words for use in rfcs|terminology", title, re.I))


def _keywords(text: str) -> List[str]:
    stop = {"the", "and", "that", "with", "shall", "must", "should", "not", "for", "from"}
    return sorted({word for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()) if word not in stop})[:20]


def _normative_levels(text: str) -> List[str]:
    values = []
    for match in NORMATIVE_PATTERN.finditer(text):
        value = re.sub(r"\s+", " ", match.group(0).upper())
        if value not in values:
            values.append(value)
    return values


def _header_numbers(header: str, field: str) -> List[str]:
    pattern = re.compile(rf"^\s*{re.escape(field)}:\s*(.+)$", re.I | re.M)
    match = pattern.search(header)
    if not match:
        return []
    return sorted(set(re.findall(r"\b(\d{3,5})\b", match.group(1))))


def write_prepared_requirements(payload: Dict[str, Any], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
