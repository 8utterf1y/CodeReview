from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .util import now


def finish_case(connection: sqlite3.Connection, repo: Path, case_id: str) -> dict:
    case = connection.execute("SELECT * FROM review_cases WHERE case_id=?", (case_id,)).fetchone()
    if not case:
        raise ValueError(f"未找到审查案例：{case_id}")
    if case["stage"] not in {"ready_to_finish", "finished"}:
        raise ValueError(f"审查案例尚不能生成报告；当前阶段为 {case['stage']}")
    runs = {
        row["stage"]: json.loads(row["result_json"])
        for row in connection.execute(
            "SELECT stage,result_json FROM stage_runs WHERE case_id=? ORDER BY submitted_at", (case_id,)
        )
    }
    final, coverage = _assemble_final(connection, case_id, runs)
    completed = coverage["remaining"] == 0
    payload = {
        "schema_version": "0.3",
        "tool": "opencode-spec-review",
        "case_id": case_id,
        "repo": case["repo"],
        "base_revision": case["base_revision"],
        "head_revision": case["head_revision"],
        "mode": case["mode"],
        "scope": json.loads(case["scope_json"]),
        "result": final,
        "coverage": coverage,
        "stage_results": runs,
        "generated_at": now(),
    }
    report_dir = repo / ".spec-review" / "reports" / case_id
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "review.json"
    markdown_path = report_dir / "review.md"
    sarif_path = report_dir / "review.sarif"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(payload), encoding="utf-8")
    sarif_path.write_text(
        json.dumps(_sarif(connection, case_id, payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    connection.execute(
        "UPDATE review_cases SET stage=?,status=?,updated_at=? WHERE case_id=?",
        ("finished" if completed else "coverage_incomplete",
         "completed" if completed else "incomplete", now(), case_id),
    )
    connection.commit()
    return {
        "case_id": case_id,
        "status": "completed" if completed else "incomplete",
        "markdown_report": str(markdown_path),
        "json_report": str(json_path),
        "sarif_report": str(sarif_path),
        "report": markdown_path.read_text(encoding="utf-8"),
    }


def _assemble_final(connection, case_id: str, runs: dict) -> tuple[dict, dict]:
    claim_rows = connection.execute(
        "SELECT claim_id,section,ordinal FROM claims WHERE case_id=? ORDER BY ordinal", (case_id,)
    ).fetchall()
    l3 = _items(runs.get("l3_review") or {}, "l3_review")
    deep = _items(runs.get("l4_converge") or {}, "l4_converge")
    by_id = {item.get("claim_id"): item for item in l3 if isinstance(item.get("claim_id"), str)}
    by_id.update({item.get("claim_id"): item for item in deep if isinstance(item.get("claim_id"), str)})
    claims = []
    for row in claim_rows:
        item = by_id.get(row["claim_id"])
        if not item:
            continue
        normalized = dict(item)
        normalized["claim_id"] = row["claim_id"]
        normalized.setdefault("section", row["section"])
        normalized["verdict"] = normalized.get("verdict") or normalized.get("status")
        claims.append(normalized)
    expected_ids = [row["claim_id"] for row in claim_rows]
    submitted_ids = {item["claim_id"] for item in claims}
    missing = [claim_id for claim_id in expected_ids if claim_id not in submitted_ids]
    counts = {name: 0 for name in ("consistent", "inconsistent", "uncertain", "not_applicable")}
    for item in claims:
        if item["verdict"] in counts:
            counts[item["verdict"]] += 1
    coverage = {
        "expected": len(expected_ids), "submitted": len(submitted_ids),
        "remaining": len(missing), "missing_claim_ids": missing,
    }
    summary = (
        f"审查完成：consistent={counts['consistent']}，inconsistent={counts['inconsistent']}，"
        f"uncertain={counts['uncertain']}，not_applicable={counts['not_applicable']}。"
        if not missing else
        f"审查未完成：仅覆盖 {len(submitted_ids)}/{len(expected_ids)} 条需求，缺少 {len(missing)} 条。"
    )
    return {
        "summary": summary,
        "verdict_counts": counts,
        "claims": claims,
        "findings": [item for item in claims if item["verdict"] == "inconsistent"],
    }, coverage


def _items(result: dict, stage: str) -> list[dict]:
    keys = ["final_verdicts", "claims", "results"] if stage == "l4_converge" else ["claims", "results"]
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _markdown(payload: dict) -> str:
    result = payload["result"] if isinstance(payload["result"], dict) else {}
    findings = result.get("findings")
    if not isinstance(findings, list):
        findings = result.get("issues") or result.get("claims") or []
    lines = [
        "# 需求—代码一致性审查报告",
        "",
        f"- 案例 ID：`{payload['case_id']}`",
        f"- 审查模式：`{payload['mode']}`",
        f"- 基准版本：`{payload['base_revision'] or '未提供'}`",
        f"- 目标版本：`{payload['head_revision']}`",
        f"- 审查类型：`{payload['scope'].get('review_type', 'comparison' if payload['base_revision'] else 'snapshot')}`",
        f"- 覆盖率：`{payload['coverage']['submitted']}/{payload['coverage']['expected']}`",
        "",
        "## 审查结论",
        "",
        str(result.get("summary") or result.get("verdict") or "审查已完成，具体发现见下文。"),
        "",
        "## 问题清单",
        "",
    ]
    pull = payload["scope"].get("pull_request")
    if isinstance(pull, dict):
        lines[2:2] = [
            f"- GitHub PR：[{pull.get('owner')}/{pull.get('repo')}#{pull.get('number')}]({pull.get('html_url')})",
            f"- PR 分支：`{pull.get('base_ref')}` ← `{pull.get('head_ref')}`",
        ]
    if not findings:
        lines.append("没有提交需要报告的问题。")
    for index, item in enumerate(findings, 1):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("claim_id") or f"问题 {index}"
        lines.extend([
            f"### {index}. {title}", "",
            f"- 判定：`{item.get('verdict') or item.get('status') or 'unknown'}`",
            f"- 严重级别：`{item.get('severity') or 'unspecified'}`",
            f"- 变更归因：`{item.get('attribution') or 'unattributed'}`",
            "",
            str(item.get("reasoning") or item.get("reason") or item.get("summary") or item.get("description") or ""),
            "",
        ])
        evidence = item.get("evidence_ids") or item.get("evidence") or []
        if evidence:
            lines.append("证据：" + ", ".join(f"`{value}`" for value in evidence))
            lines.append("")
        if isinstance(item.get("suggested_patch"), str) and item["suggested_patch"].strip():
            lines.extend(["建议 Patch（不会自动应用）：", "", "```diff", item["suggested_patch"].rstrip(), "```", ""])
    lines.extend([
        "## 审查范围", "", "```json",
        json.dumps(payload["scope"], ensure_ascii=False, indent=2), "```", "",
    ])
    return "\n".join(lines)


def _sarif(connection: sqlite3.Connection, case_id: str, payload: dict) -> dict:
    rules = []
    results = []
    for finding in payload["result"].get("findings", []):
        claim_id = str(finding.get("claim_id") or "SPEC-REVIEW")
        title = str(finding.get("title") or claim_id)
        rules.append({
            "id": claim_id,
            "name": "RequirementCodeInconsistency",
            "shortDescription": {"text": title},
        })
        evidence = None
        for evidence_id in finding.get("evidence_ids") or finding.get("evidence") or []:
            row = connection.execute(
                "SELECT path,start_line,end_line FROM evidence WHERE case_id=? AND evidence_id=?",
                (case_id, evidence_id),
            ).fetchone()
            if row and row["path"] and row["start_line"]:
                evidence = row
                break
        result = {
            "ruleId": claim_id,
            "level": _sarif_level(finding.get("severity")),
            "message": {"text": str(
                finding.get("reasoning") or finding.get("reason") or finding.get("summary") or title
            )},
            "properties": {
                "case_id": case_id,
                "attribution": finding.get("attribution") or "unattributed",
            },
        }
        if evidence:
            result["locations"] = [{
                "physicalLocation": {
                    "artifactLocation": {"uri": evidence["path"]},
                    "region": {
                        "startLine": evidence["start_line"],
                        "endLine": evidence["end_line"] or evidence["start_line"],
                    },
                }
            }]
        results.append(result)
    unique_rules = {rule["id"]: rule for rule in rules}
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "opencode-spec-review", "version": "0.4.0",
                "informationUri": "https://github.com/",
                "rules": list(unique_rules.values()),
            }},
            "results": results,
        }],
    }


def _sarif_level(severity) -> str:
    return {
        "critical": "error", "high": "error", "medium": "warning",
        "low": "note", "info": "note",
    }.get(str(severity or "").lower(), "warning")
