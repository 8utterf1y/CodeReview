from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .checkers import run_all_checkers
from .code_index import CodeIndex
from .report import write_json, write_markdown
from .spec_loader import extract_requirements


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="specdiff",
        description="Detect inconsistencies between design/RFC documents and code implementations.",
    )
    parser.add_argument("--repo", required=True, help="Path to the implementation repository.")
    parser.add_argument("--docs", required=True, help="Path to a spec/design document file or directory.")
    parser.add_argument("--out", required=True, help="Path to write machine-readable issues JSON.")
    parser.add_argument("--report", help="Optional path to write a Markdown report.")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Only emit findings with confidence greater than or equal to this value.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    docs = Path(args.docs).resolve()
    out = Path(args.out).resolve()
    report = Path(args.report).resolve() if args.report else None

    try:
        requirements = extract_requirements(docs)
        index = CodeIndex(repo)
        findings = [
            finding
            for finding in run_all_checkers(index, requirements)
            if finding.confidence >= args.min_confidence
        ]
        payload = {
            "tool": "specdiff",
            "version": __version__,
            "repo": str(repo),
            "docs": str(docs),
            "requirements_indexed": len(requirements),
            "source_files_indexed": len(index.files),
            "issues": [finding.to_dict() for finding in findings],
        }
        write_json(out, payload)
        if report:
            write_markdown(report, findings)
    except Exception as exc:
        print(f"specdiff error: {exc}", file=sys.stderr)
        return 2
    return 0
