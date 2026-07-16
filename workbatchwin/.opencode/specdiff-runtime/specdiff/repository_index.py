from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .codefacts import build_codefacts, export_codefacts


LANGUAGES = {
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".py": "python", ".go": "go", ".rs": "rust",
    ".java": "java", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".sh": "shell", ".s": "assembly", ".S": "assembly",
}
BUILD_NAMES = {
    "Makefile": "make", "makefile": "make", "GNUmakefile": "make",
    "CMakeLists.txt": "cmake", "meson.build": "meson", "BUILD": "bazel",
    "BUILD.bazel": "bazel", "WORKSPACE": "bazel", "Cargo.toml": "cargo",
    "go.mod": "go", "package.json": "node", "pyproject.toml": "python",
}
SKIP_DIRS = {
    ".git", ".specdiff", ".opencode", ".codex", ".agents",
    "node_modules", ".venv", "venv", "__pycache__", "dist",
}


def build_repository_index(repo: Path, out_dir: Path) -> Dict[str, Any]:
    repo = repo.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    files = list(_scan_files(repo))
    components = _components(files)
    builds = _build_graph(repo, files)
    tools = _tool_coverage(files)
    codefacts = build_codefacts(repo, out_dir / "codefacts.sqlite", files, builds)
    export_codefacts(out_dir / "codefacts.sqlite", out_dir)
    tools["codefacts"] = codefacts
    counts = codefacts["counts"]
    tools["capabilities"].update({
        "symbols": "syntax" if counts["symbols"] else "unavailable",
        "references": "syntax" if counts["refs"] else "unavailable",
        "call_graph": "candidate" if counts["calls"] else "unavailable",
        "pattern_hits": "available_empty" if counts["pattern_hits"] == 0 else "syntax",
    })
    repository = {
        "schema_version": "1.0",
        "repository_root": str(repo),
        "revision": _revision(repo),
        "files_indexed": len(files),
        "languages": dict(sorted(Counter(item["language"] for item in files if item["language"]).items())),
        "build_systems": sorted({item["build_system"] for item in builds["build_files"]}),
        "components": len(components),
        "index_capabilities": [
            "files", "components", "build", "text_query", "source_read",
            "aider_tree_sitter_tags", "repo_map", "symbol_candidates", "reference_candidates",
        ],
    }
    _write_json(out_dir / "repository.json", repository)
    _write_jsonl(out_dir / "files.jsonl", files)
    _write_json(out_dir / "components.json", {"components": components})
    _write_json(out_dir / "build_graph.json", builds)
    _write_json(out_dir / "tool_coverage.json", tools)
    return repository


def load_repository(index_dir: Path) -> Dict[str, Any]:
    return json.loads((index_dir / "repository.json").read_text(encoding="utf-8"))


def load_files(index_dir: Path) -> List[Dict[str, Any]]:
    path = index_dir / "files.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _scan_files(repo: Path) -> Iterable[Dict[str, Any]]:
    counter = 1
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(repo).parts):
            continue
        language = LANGUAGES.get(path.suffix)
        build_system = BUILD_NAMES.get(path.name)
        if not language and not build_system:
            continue
        rel = str(path.relative_to(repo))
        data = path.read_bytes()
        yield {
            "file_id": f"F-{counter:07d}",
            "path": rel,
            "language": language,
            "component": _component_name(rel),
            "role": _role(rel),
            "size": len(data),
            "line_count": data.count(b"\n") + (1 if data else 0),
            "sha256": hashlib.sha256(data).hexdigest(),
            "build_system": build_system,
            "role_source": "path_heuristic",
            "build_status": "build_config" if build_system else "unknown",
        }
        counter += 1


def _components(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in files:
        grouped[item["component"]].append(item)
    result = []
    for index, (name, members) in enumerate(sorted(grouped.items()), 1):
        result.append({
            "component_id": f"C-{index:05d}",
            "name": name,
            "file_count": len(members),
            "roles": dict(sorted(Counter(item["role"] for item in members).items())),
            "languages": dict(sorted(Counter(item["language"] for item in members if item["language"]).items())),
            "sample_files": [item["path"] for item in members[:20]],
        })
    return result


def _build_graph(repo: Path, files: List[Dict[str, Any]]) -> Dict[str, Any]:
    build_files = []
    for item in files:
        if not item["build_system"]:
            continue
        includes: List[str] = []
        try:
            text = (repo / item["path"]).read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(("include ", "-include ", "subdir(")):
                    includes.append(stripped[:300])
        except OSError:
            pass
        build_files.append({
            "file_id": item["file_id"], "path": item["path"],
            "build_system": item["build_system"], "component": item["component"],
            "includes": includes[:100],
        })
    return {
        "build_files": build_files,
        "compile_commands": {
            "available": (repo / "compile_commands.json").exists(),
            "path": "compile_commands.json" if (repo / "compile_commands.json").exists() else None,
        },
        "note": "V1 records build files and direct include/subdir statements; target/source edges require a later parser.",
    }


def _tool_coverage(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    source_count = sum(1 for item in files if item["language"])
    detected = {}
    for name in ("ctags", "clang", "clangd", "tree-sitter", "scip", "scip-clang", "codeql", "joern", "semgrep"):
        detected[name] = {"available": bool(shutil.which(name)), "path": shutil.which(name)}
    return {
        "files_discovered": len(files),
        "source_files_discovered": source_count,
        "v1_indexed_files": len(files),
        "v1_coverage": 1.0 if files else 0.0,
        "capabilities": {
            "files": "available", "components": "available", "build": "partial",
            "text_query": "available", "source_read": "available",
            "ast": "unavailable", "precise_symbols": "unavailable",
            "references": "unavailable", "call_graph": "unavailable", "data_flow": "unavailable",
        },
        "detected_tools": detected,
    }


def _component_name(rel: str) -> str:
    parts = Path(rel).parts
    if not parts:
        return "."
    if parts[0] in {"src", "lib", "app", "apps", "freebsd", "dpdk", "packages", "modules", "services"} and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def _role(rel: str) -> str:
    parts = {part.lower() for part in Path(rel).parts}
    if parts & {"test", "tests", "testing"}: return "test"
    if parts & {"example", "examples", "demo", "demos"}: return "example"
    if parts & {"vendor", "vendors", "third_party", "third-party", "contrib"}: return "vendor"
    if parts & {"generated", "gen"}: return "generated"
    if parts & {"doc", "docs"}: return "documentation"
    return "production"


def _revision(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
