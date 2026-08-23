# SpecDiff Work 目录说明

## 1. 作品概述

本目录是 SpecDiff 的可运行交付件目录，包含 OpenCode 命令、Agent、工具、Skill 和 Python runtime。评测或使用时从本目录启动 OpenCode，并通过 `/spec-audit` 传入待审计代码目录、规范文档和输出路径。

## 2. 输入

| 输入项 | 说明 |
|--------|------|
| 待审计代码目录 | 要检查的代码仓库或项目目录 |
| 规范/设计文档 | Markdown、requirements JSON 或 RFC 清单 |
| 输出文件路径 | `issues.json` 的生成位置 |

## 3. 执行工作流

### Step 1：启动 OpenCode

```bash
opencode
```

预期状态：

```text
OpenCode 加载 .opencode/ 下的 spec-audit 命令和工具
```

### Step 2：运行审计

```text
/spec-audit <待审计代码目录> <规范或设计文档路径> <输出issues.json路径>
```

该命令会依次执行：

```text
audit_start
audit_next
Code Investigator 调查 Batch
submit_batch_results
audit_finish
```

运行时生成的中间状态保存在待审计代码目录的 `.specdiff/audit/` 下。

### Step 3：读取输出

主输出为命令传入的 `issues.json` 路径，同时会在待审计代码目录下生成：

```text
.specdiff/issues.sarif
.specdiff/audit/
```

## 4. 产物清单

| 产物 | 位置 | 格式 | 用途 |
|------|------|------|------|
| OpenCode 命令 | `.opencode/commands/spec-audit.md` | Markdown | 提供 `/spec-audit` 入口 |
| Orchestrator Agent | `.opencode/agents/spec-compliance-orchestrator.md` | Markdown | 编排审计流程 |
| Investigator Agent | `.opencode/agents/code-investigator.md` | Markdown | 调查代码证据并提交 Batch 结果 |
| OpenCode 工具 | `.opencode/tools/` | TypeScript | 调用 runtime API |
| SpecDiff runtime | `specdiff/` | Python 包 | 执行解析、索引、规划、状态管理和报告生成 |
| Skill | `skills/spec-code-consistency/SKILL.md` | Markdown | 描述审计方法和证据规则 |
| 主报告 | `<输出issues.json路径>` | JSON | 不一致问题列表 |
| 审计过程 | `<待审计代码目录>/.specdiff/audit/` | JSON/JSONL/SQLite | 查询、证据、Batch 和代码索引 |

