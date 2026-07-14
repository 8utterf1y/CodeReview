from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List

from .models import Requirement


TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc", ".html", ".htm"}
SKIP_SPEC_DIRS = {".specdiff", "q", "results", "result", "reports", "report", "outputs", "output"}


def load_spec_texts(path: Path) -> List[tuple[str, str]]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"docs path does not exist: {path}")
    if path == Path(path.anchor):
        raise ValueError(f"refusing to scan filesystem root as specification input: {path}")
    if path.is_file() and path.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError(f"unsupported specification file type: {path.suffix or '<none>'}")

    files: Iterable[Path]
    if path.is_dir():
        files = sorted(
            p
            for p in path.rglob("*")
            if p.is_file()
            and p.suffix.lower() in TEXT_SUFFIXES
            and not any(part in SKIP_SPEC_DIRS for part in p.relative_to(path).parts[:-1])
        )
        if len(files) > 1000:
            raise ValueError(f"specification directory contains too many text files ({len(files)} > 1000): {path}")
    else:
        files = [path]

    texts: List[tuple[str, str]] = []
    for file in files:
        if file.suffix.lower() not in TEXT_SUFFIXES and path.is_dir():
            continue
        try:
            texts.append((str(file), file.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return texts


def extract_requirements(path: Path, *, include_builtin_hints: bool = False) -> List[Requirement]:
    del include_builtin_hints
    texts = load_spec_texts(path)
    requirements: List[Requirement] = []
    counter = 1
    for name, text in texts:
        current_section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            header = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if header:
                current_section = header.group(2).strip()
            if _looks_like_requirement(stripped):
                requirements.append(
                    Requirement(
                        id=f"DOC-{counter:04d}",
                        document=name,
                        section=current_section or "unknown",
                        quote=stripped[:600],
                        normalized=stripped[:600],
                        keywords=_keywords(stripped),
                    )
                )
                counter += 1

    return requirements


def extract_audit_requirements(path: Path) -> List[Requirement]:
    """Load a canonical requirement JSON, or extract only explicit document obligations.

    A table of standards, links, or reference material defines review scope, not a code obligation.
    It must therefore be expanded into a requirement JSON before it can drive an audit.
    """
    path = path.expanduser().resolve()
    if path.suffix.lower() == ".json":
        return _load_requirement_json(path)
    return extract_requirements(path)


def _load_requirement_json(path: Path) -> List[Requirement]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid requirement JSON: {path}: {exc.msg}") from exc
    rows = payload.get("requirements") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("requirement JSON must contain a requirements array")
    requirements: List[Requirement] = []
    seen_ids = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"requirements[{index - 1}] must be an object")
        required = ("id", "document", "quote", "normalized")
        missing = [field for field in required if not isinstance(row.get(field), str) or not row[field].strip()]
        if missing:
            raise ValueError(f"requirements[{index - 1}] is missing non-empty fields: {', '.join(missing)}")
        req_id = row["id"].strip()
        if req_id in seen_ids:
            raise ValueError(f"duplicate requirement id: {req_id}")
        seen_ids.add(req_id)
        keywords = row.get("keywords") or []
        if not isinstance(keywords, list) or not all(isinstance(item, str) for item in keywords):
            raise ValueError(f"requirements[{index - 1}].keywords must be a string array")
        requirements.append(Requirement(
            id=req_id, document=row["document"].strip(), section=str(row.get("section") or "unknown"),
            quote=row["quote"].strip(), normalized=row["normalized"].strip(), keywords=keywords,
            source=str(row.get("source") or "parsed_requirement_json"),
        ))
    return requirements


def extract_model_candidates(path: Path) -> List[Requirement]:
    """Return normative requirements plus structured reference/list entries for agent interpretation."""
    requirements = extract_requirements(path)
    seen = {(item.document, item.quote) for item in requirements}
    counter = len(requirements) + 1
    for name, text in load_spec_texts(path):
        current_section = ""
        for line in text.splitlines():
            stripped = line.strip()
            header = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if header:
                current_section = header.group(2).strip()
                continue
            if not _looks_like_structured_candidate(stripped) or (name, stripped) in seen:
                continue
            requirements.append(
                Requirement(
                    id=f"SRC-{counter:04d}",
                    document=name,
                    section=current_section or "unknown",
                    quote=stripped[:600],
                    normalized=stripped[:600],
                    keywords=_keywords(stripped),
                    source="reference_candidate",
                )
            )
            seen.add((name, stripped))
            counter += 1
    return requirements


def find_requirement(requirements: List[Requirement], req_id: str) -> Requirement:
    for req in requirements:
        if req.id == req_id:
            return req
    raise KeyError(req_id)


def _looks_like_requirement(text: str) -> bool:
    if re.search(
        r"\b(MUST|MUST NOT|SHOULD|SHOULD NOT|REQUIRED|SHALL|SHALL NOT|"
        r"REQUIRES?|SUPPORTS?|HANDLES?|PROVIDES?|ENSURES?|VALIDATES?|REJECTS?|"
        r"FORBIDS?|PROHIBITS?)\b",
        text,
        re.I,
    ):
        return True
    if re.search(r"(必须|不得|禁止|应当|应该|需要|要求|支持|提供|处理|校验|拒绝|保证|确保)", text):
        return True
    if re.match(r"^\s*[-*]\s+[^:]{3,80}:\s*(must|should|required|支持|必须|需要|应当)", text, re.I):
        return True
    return False


def _looks_like_structured_candidate(text: str) -> bool:
    if not text or re.match(r"^\|?\s*:?-{3,}", text):
        return False
    if re.match(r"^\|.*\|$", text) and re.search(r"\b(RFC\s*\d+|requirement|feature|shall|must|should)\b", text, re.I):
        return True
    return bool(
        re.match(r"^\s*(?:[-*]|\d+[.)])\s+", text)
        and re.search(r"\b(RFC\s*\d+|must|should|shall|required|support)\b", text, re.I)
    )


def _keywords(text: str) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    stop = {"the", "and", "that", "with", "shall", "must", "should", "not", "for", "from"}
    return sorted({word for word in words if word not in stop})[:20]
