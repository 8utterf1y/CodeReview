from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


VENDOR_DIR = Path(__file__).resolve().parent.parent / "specdiff-vendor-slim"
if VENDOR_DIR.exists() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS files (
  file_id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, language TEXT, source_role TEXT NOT NULL,
  role_source TEXT NOT NULL, component TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
  line_count INTEGER NOT NULL, build_system TEXT, build_status TEXT
);
CREATE TABLE IF NOT EXISTS symbols (
  symbol_id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, file_id TEXT NOT NULL,
  start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, scope TEXT, signature TEXT,
  backend TEXT NOT NULL, precision TEXT NOT NULL, FOREIGN KEY(file_id) REFERENCES files(file_id)
);
CREATE INDEX IF NOT EXISTS symbols_name_idx ON symbols(name);
CREATE TABLE IF NOT EXISTS refs (
  reference_id TEXT PRIMARY KEY, name TEXT NOT NULL, symbol_id TEXT, file_id TEXT NOT NULL,
  line INTEGER NOT NULL, role TEXT NOT NULL, backend TEXT NOT NULL, precision TEXT NOT NULL,
  FOREIGN KEY(symbol_id) REFERENCES symbols(symbol_id), FOREIGN KEY(file_id) REFERENCES files(file_id)
);
CREATE INDEX IF NOT EXISTS refs_symbol_idx ON refs(symbol_id);
CREATE TABLE IF NOT EXISTS calls (
  call_id TEXT PRIMARY KEY, caller_symbol_id TEXT, callee_name TEXT NOT NULL, callee_symbol_id TEXT, file_id TEXT NOT NULL,
  line INTEGER NOT NULL, backend TEXT NOT NULL, resolution TEXT NOT NULL, confidence REAL NOT NULL,
  FOREIGN KEY(caller_symbol_id) REFERENCES symbols(symbol_id),
  FOREIGN KEY(callee_symbol_id) REFERENCES symbols(symbol_id), FOREIGN KEY(file_id) REFERENCES files(file_id)
);
CREATE TABLE IF NOT EXISTS pattern_hits (
  hit_id TEXT PRIMARY KEY, query_id TEXT, pattern TEXT NOT NULL, language TEXT, file_id TEXT NOT NULL,
  start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, symbol_id TEXT, backend TEXT NOT NULL,
  capture_json TEXT NOT NULL, FOREIGN KEY(file_id) REFERENCES files(file_id)
);
CREATE TABLE IF NOT EXISTS build_units (
  unit_id TEXT PRIMARY KEY, path TEXT NOT NULL, build_system TEXT NOT NULL, component TEXT NOT NULL,
  metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_runs (
  tool TEXT PRIMARY KEY, available INTEGER NOT NULL, executed INTEGER NOT NULL, version TEXT,
  files_attempted INTEGER NOT NULL DEFAULT 0, files_succeeded INTEGER NOT NULL DEFAULT 0,
  precision TEXT NOT NULL, impact TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS repo_rank (
  file_id TEXT PRIMARY KEY, rank REAL NOT NULL, FOREIGN KEY(file_id) REFERENCES files(file_id)
);
"""


def build_codefacts(
    repo: Path,
    db_path: Path,
    files: List[Dict[str, Any]],
    build_graph: Dict[str, Any],
) -> Dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SCHEMA)
        _insert_files(connection, files)
        _insert_build_units(connection, build_graph)
        tag_result = _extract_aider_tags(repo, files)
        _insert_tags(connection, files, tag_result["tags"])
        _build_reference_links(connection)
        _build_repo_rank(connection)
        _insert_tool_runs(connection, tag_result["tool_runs"])
        connection.commit()
        stats = _stats(connection)
    finally:
        connection.close()
    return stats


def export_codefacts(db_path: Path, out_dir: Path) -> None:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        for table, filename in (
            ("files", "files.jsonl"), ("symbols", "symbols.jsonl"), ("refs", "references.jsonl"),
            ("calls", "calls.jsonl"), ("pattern_hits", "pattern_hits.jsonl"),
        ):
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
            _write_jsonl(out_dir / filename, rows)
        rank_rows = [dict(row) for row in connection.execute(
            "SELECT f.path, r.rank FROM repo_rank r JOIN files f USING(file_id) ORDER BY r.rank DESC LIMIT 500"
        )]
        (out_dir / "repo-map.json").write_text(
            json.dumps({"backend": "aider_tree_sitter_pagerank", "files": rank_rows}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    finally:
        connection.close()


def query_codefacts(
    db_path: Path, mode: str, query: str = "", path: str = "", start: int = 1,
    end: int = 200, limit: int = 50,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        if mode == "symbol":
            rows = connection.execute(
                "SELECT s.*, f.path, f.source_role FROM symbols s JOIN files f USING(file_id) "
                "WHERE lower(s.name) LIKE ? ORDER BY f.source_role='production' DESC, s.name LIMIT ?",
                (f"%{query.lower()}%", limit),
            ).fetchall()
        elif mode == "references":
            rows = connection.execute(
                "SELECT r.*, f.path, s.name AS target_name FROM refs r JOIN files f USING(file_id) "
                "LEFT JOIN symbols s USING(symbol_id) WHERE lower(r.name) LIKE ? OR r.symbol_id=? LIMIT ?",
                (f"%{query.lower()}%", query, limit),
            ).fetchall()
        elif mode in {"callers", "callees"}:
            side = "callee" if mode == "callers" else "caller"
            if mode == "callers":
                rows = connection.execute(
                    "SELECT c.*, f.path, caller.name AS caller_name, callee.name AS resolved_callee_name "
                    "FROM calls c JOIN files f USING(file_id) "
                    "LEFT JOIN symbols caller ON caller.symbol_id=c.caller_symbol_id "
                    "LEFT JOIN symbols callee ON callee.symbol_id=c.callee_symbol_id "
                    "WHERE lower(c.callee_name) LIKE ? OR c.callee_symbol_id=? LIMIT ?",
                    (f"%{query.lower()}%", query, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT c.*, f.path, caller.name AS caller_name, callee.name AS resolved_callee_name "
                    "FROM calls c JOIN files f USING(file_id) "
                    "LEFT JOIN symbols caller ON caller.symbol_id=c.caller_symbol_id "
                    "LEFT JOIN symbols callee ON callee.symbol_id=c.callee_symbol_id "
                    "WHERE lower(caller.name) LIKE ? OR c.caller_symbol_id=? LIMIT ?",
                    (f"%{query.lower()}%", query, limit),
                ).fetchall()
        elif mode == "component":
            rows = connection.execute(
                "SELECT * FROM files WHERE component=? ORDER BY path LIMIT ?", (query, limit)
            ).fetchall()
        elif mode == "build":
            rows = connection.execute(
                "SELECT * FROM build_units WHERE lower(path || ' ' || metadata_json) LIKE ? LIMIT ?",
                (f"%{query.lower()}%", limit),
            ).fetchall()
        elif mode == "source":
            row = connection.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
            if not row:
                raise ValueError(f"path is not indexed: {path}")
            return [], {"source_file": dict(row), "start": start, "end": end}
        elif mode == "repo_map":
            rows = connection.execute(
                "SELECT f.*, r.rank FROM repo_rank r JOIN files f USING(file_id) ORDER BY r.rank DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            return [], {"status": "tool_limited", "detail": f"Code Facts mode not available: {mode}"}
        return [dict(row) for row in rows], {"status": "completed", "backend": "sqlite_codefacts", "coverage": _coverage_summary(connection)}
    finally:
        connection.close()


def _extract_aider_tags(repo: Path, files: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        from tree_sitter import Language, Parser
    except ImportError as exc:
        return {
            "tags": [],
            "tool_runs": [{"tool": "aider-tree-sitter", "available": 0, "executed": 0,
                           "precision": "syntax", "impact": "symbol/reference index unavailable", "detail": str(exc)}],
        }
    query_dir = Path(__file__).resolve().parent / "queries" / "aider-tree-sitter-language-pack"
    tags: List[Dict[str, Any]] = []
    attempted = succeeded = 0
    failures: List[str] = []
    for item in files:
        if not item.get("language"):
            continue
        lang = _tree_sitter_lang(item["path"])
        query_name = "typescript" if lang == "tsx" else lang
        query_path = query_dir / f"{query_name}-tags.scm" if query_name else None
        if not lang or not query_path or not query_path.exists():
            continue
        attempted += 1
        try:
            source = (repo / item["path"]).read_bytes()
            language = Language(_grammar_capsule(lang))
            parser = Parser(language)
            tree = parser.parse(source)
            captures = language.query(query_path.read_text(encoding="utf-8")).captures(tree.root_node)
            capture_rows = [(node, tag) for tag, nodes in captures.items() for node in nodes]
            definitions = [(node, tag) for node, tag in capture_rows if tag.startswith("definition.")]
            for node, tag in capture_rows:
                if not tag.startswith(("name.definition.", "name.reference.")):
                    continue
                role = "definition" if tag.startswith("name.definition.") else "reference"
                kind = tag.split(".")[-1]
                end_line = node.end_point[0] + 1
                if role == "definition":
                    containers = [
                        definition for definition, definition_tag in definitions
                        if definition_tag.endswith(kind)
                        and definition.start_byte <= node.start_byte <= node.end_byte <= definition.end_byte
                    ]
                    if containers:
                        end_line = min(containers, key=lambda candidate: candidate.end_byte - candidate.start_byte).end_point[0] + 1
                tags.append({
                    "name": source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                    "kind": kind, "role": role, "file_id": item["file_id"],
                    "line": node.start_point[0] + 1, "end_line": end_line,
                    "backend": "aider_tree_sitter_tags", "precision": "syntax",
                })
            succeeded += 1
        except Exception as exc:
            failures.append(f"{item['path']}: {exc}")
    return {
        "tags": tags,
        "tool_runs": [{
            "tool": "aider-tree-sitter", "available": 1, "executed": 1,
            "files_attempted": attempted, "files_succeeded": succeeded, "precision": "syntax",
            "impact": "unsupported or failed files lack syntax tags",
            "detail": json.dumps({"query_source": "Aider tags.scm", "failures": failures[:20]}, ensure_ascii=False),
        }],
    }


def _tree_sitter_lang(path: str) -> Optional[str]:
    suffix = Path(path).suffix.lower()
    return {
        ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
        ".hpp": "cpp", ".hh": "cpp", ".py": "python", ".go": "go", ".rs": "rust",
        ".java": "java", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
        ".tsx": "tsx",
    }.get(suffix)


def _grammar_capsule(lang: str):
    if lang == "c":
        import tree_sitter_c as grammar
        return grammar.language()
    if lang == "cpp":
        import tree_sitter_cpp as grammar
        return grammar.language()
    if lang == "python":
        import tree_sitter_python as grammar
        return grammar.language()
    if lang == "go":
        import tree_sitter_go as grammar
        return grammar.language()
    if lang == "rust":
        import tree_sitter_rust as grammar
        return grammar.language()
    if lang == "java":
        import tree_sitter_java as grammar
        return grammar.language()
    if lang == "javascript":
        import tree_sitter_javascript as grammar
        return grammar.language()
    if lang in {"typescript", "tsx"}:
        import tree_sitter_typescript as grammar
        return grammar.language_typescript() if lang == "typescript" else grammar.language_tsx()
    raise ValueError(f"unsupported Tree-sitter language: {lang}")


def _insert_files(connection: sqlite3.Connection, files: List[Dict[str, Any]]) -> None:
    connection.executemany(
        "INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [(
            item["file_id"], item["path"], item.get("language"), item["role"], item.get("role_source", "path_heuristic"),
            item["component"], item["sha256"], item["size"], item["line_count"], item.get("build_system"),
            item.get("build_status"),
        ) for item in files],
    )


def _insert_build_units(connection: sqlite3.Connection, build_graph: Dict[str, Any]) -> None:
    rows = []
    for index, item in enumerate(build_graph.get("build_files", []), 1):
        rows.append((f"BU-{index:07d}", item["path"], item["build_system"], item["component"], json.dumps(item, ensure_ascii=False)))
    connection.executemany("INSERT INTO build_units VALUES(?,?,?,?,?)", rows)


def _insert_tags(connection: sqlite3.Connection, files: List[Dict[str, Any]], tags: List[Dict[str, Any]]) -> None:
    symbol_rows = []
    reference_rows = []
    for tag in tags:
        if tag["role"] == "definition":
            symbol_rows.append((
                f"S-{len(symbol_rows)+1:09d}", tag["name"], tag["kind"], tag["file_id"], tag["line"],
                tag["end_line"], None, None, tag["backend"], tag["precision"],
            ))
        else:
            reference_rows.append((
                f"R-{len(reference_rows)+1:010d}", tag["name"], None, tag["file_id"], tag["line"],
                tag["kind"], tag["backend"], tag["precision"],
            ))
    connection.executemany("INSERT INTO symbols VALUES(?,?,?,?,?,?,?,?,?,?)", symbol_rows)
    connection.executemany("INSERT INTO refs VALUES(?,?,?,?,?,?,?,?)", reference_rows)


def _build_reference_links(connection: sqlite3.Connection) -> None:
    definitions: Dict[str, List[sqlite3.Row]] = defaultdict(list)
    for row in connection.execute("SELECT s.*, f.component FROM symbols s JOIN files f USING(file_id)"):
        definitions[row["name"]].append(row)
    refs = connection.execute("SELECT r.*, f.component FROM refs r JOIN files f USING(file_id)").fetchall()
    for ref in refs:
        candidates = definitions.get(ref["name"], [])
        if not candidates:
            continue
        same_component = [item for item in candidates if item["component"] == ref["component"]]
        selected = (same_component or candidates)[0]
        connection.execute("UPDATE refs SET symbol_id=? WHERE reference_id=?", (selected["symbol_id"], ref["reference_id"]))
        if ref["role"] != "call":
            continue
        caller = connection.execute(
            "SELECT * FROM symbols WHERE file_id=? AND start_line<=? AND end_line>=? "
            "AND kind IN ('function','method') ORDER BY end_line-start_line LIMIT 1",
            (ref["file_id"], ref["line"], ref["line"]),
        ).fetchone()
        if caller:
            count = connection.execute("SELECT count(*) FROM calls").fetchone()[0] + 1
            connection.execute(
                "INSERT INTO calls VALUES(?,?,?,?,?,?,?,?,?)",
                (f"CALL-{count:010d}", caller["symbol_id"], ref["name"], selected["symbol_id"], ref["file_id"], ref["line"],
                 "aider_tree_sitter_tags", "probable", 0.55),
            )


def _build_repo_rank(connection: sqlite3.Connection) -> None:
    try:
        import networkx as nx
    except ImportError:
        for row in connection.execute("SELECT file_id FROM files"):
            connection.execute("INSERT INTO repo_rank VALUES(?,?)", (row["file_id"], 1.0))
        return
    graph = nx.MultiDiGraph()
    files = [row[0] for row in connection.execute("SELECT file_id FROM files")]
    graph.add_nodes_from(files)
    for row in connection.execute(
        "SELECT r.file_id AS source, s.file_id AS target FROM refs r JOIN symbols s USING(symbol_id)"
    ):
        graph.add_edge(row["source"], row["target"], weight=1.0)
    try:
        rank = nx.pagerank(graph) if graph.number_of_nodes() else {}
    except ModuleNotFoundError:
        rank = nx.in_degree_centrality(graph) if graph.number_of_nodes() > 1 else {item: 1.0 for item in files}
    connection.executemany("INSERT INTO repo_rank VALUES(?,?)", [(file_id, rank.get(file_id, 0.0)) for file_id in files])


def _insert_tool_runs(connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> None:
    connection.executemany(
        "INSERT INTO tool_runs(tool,available,executed,version,files_attempted,files_succeeded,precision,impact,detail) VALUES(?,?,?,?,?,?,?,?,?)",
        [(
            item["tool"], item.get("available", 0), item.get("executed", 0), item.get("version"),
            item.get("files_attempted", 0), item.get("files_succeeded", 0), item["precision"],
            item.get("impact"), item.get("detail"),
        ) for item in rows],
    )


def _stats(connection: sqlite3.Connection) -> Dict[str, Any]:
    counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("files", "symbols", "refs", "calls", "pattern_hits", "build_units")}
    tools = [dict(row) for row in connection.execute("SELECT * FROM tool_runs")]
    return {"counts": counts, "tool_runs": tools}


def _coverage_summary(connection: sqlite3.Connection) -> Dict[str, Any]:
    tool = connection.execute("SELECT * FROM tool_runs WHERE tool='aider-tree-sitter'").fetchone()
    symbols = connection.execute("SELECT count(*) FROM symbols").fetchone()[0]
    refs = connection.execute("SELECT count(*) FROM refs").fetchone()[0]
    calls = connection.execute("SELECT count(*) FROM calls").fetchone()[0]
    if tool and tool["available"] and tool["executed"]:
        ratio = (tool["files_succeeded"] / tool["files_attempted"]) if tool["files_attempted"] else 0
        tree_sitter = "available" if ratio >= 0.8 else "partial"
    else:
        tree_sitter = "unavailable"
    return {
        "tree_sitter": tree_sitter,
        "symbol_index": "good" if symbols else "unavailable",
        "reference_index": "partial" if refs else "unavailable",
        "call_index": "heuristic" if calls else "unavailable",
    }


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
