from __future__ import annotations

from typing import List

from .code_index import CodeIndex
from .models import Finding, Requirement


def run_all_checkers(_index: CodeIndex, _requirements: List[Requirement]) -> List[Finding]:
    """Compatibility shim.

    Benchmark-specific known-answer checkers are regression fixtures, not production audit logic.
    The OpenCode audit path is driven by requirements, Code Facts, batch investigation, and assembly.
    """
    return []
