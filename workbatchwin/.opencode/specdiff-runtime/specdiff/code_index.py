from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Pattern, Union

from .models import CodeHit


CODE_SUFFIXES = {
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hpp",
    ".hh",
    ".py",
    ".go",
    ".rs",
    ".java",
    ".js",
    ".ts",
}

SKIP_DIRS = {".git", "build", "dist", "node_modules", ".venv", "venv", "__pycache__"}


class CodeIndex:
    def __init__(self, repo: Path) -> None:
        if not repo.exists():
            raise FileNotFoundError(f"repo path does not exist: {repo}")
        self.repo = repo
        self.files = list(self._iter_code_files())

    def _iter_code_files(self) -> Iterable[Path]:
        for path in self.repo.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in CODE_SUFFIXES:
                yield path

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.repo))
        except ValueError:
            return str(path)

    def read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def search(
        self,
        pattern: Union[str, Pattern[str]],
        *,
        file_regex: Optional[str] = None,
        flags: int = re.I,
        max_hits: int = 50,
    ) -> List[CodeHit]:
        regex = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        file_re = re.compile(file_regex) if file_regex else None
        hits: List[CodeHit] = []
        for path in self.files:
            rel = self.rel(path)
            if file_re and not file_re.search(rel):
                continue
            try:
                lines = self.read(path).splitlines()
            except OSError:
                continue
            for idx, line in enumerate(lines, 1):
                if regex.search(line):
                    hits.append(CodeHit(file=rel, line=idx, quote=line.strip()[:500]))
                    if len(hits) >= max_hits:
                        return hits
        return hits

    def file_text_by_rel_suffix(self, suffix: str) -> tuple[Optional[Path], str]:
        for path in self.files:
            if self.rel(path).endswith(suffix):
                try:
                    return path, self.read(path)
                except OSError:
                    return path, ""
        return None, ""

    def contains_any(self, terms: List[str], *, file_regex: Optional[str] = None) -> List[CodeHit]:
        escaped = "|".join(re.escape(term) for term in terms)
        if not escaped:
            return []
        return self.search(escaped, file_regex=file_regex)
