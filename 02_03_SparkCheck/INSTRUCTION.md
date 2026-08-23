# SpecDiff 代码-规范一致性检视作品说明

## 1. 作品概述

本作品提供一个基于 OpenCode 的代码实现与设计文档/RFC 规范一致性检视工具。工具读取待审计代码目录和规范文档，构建代码事实索引，将规范要求拆分为可追溯的审计任务，并由 Agent 使用受控工具检索代码证据，最终生成结构化 `issues.json` 和 SARIF 报告。

作品可用于发现以下类型的不一致：

```text
规范要求未实现
实现行为弱于规范要求
实现只覆盖部分边界条件
代码路径、配置或协议处理与文档描述不一致
```

## 2. 输入

| 输入项 | 说明 |
|--------|------|
| 待审计代码目录 | 需要检视的代码仓库或项目目录 |
| 规范/设计文档 | 描述期望行为的 Markdown、requirements JSON 或 RFC 清单 |
| 输出文件路径 | 生成 `issues.json` 的目标路径；通常放在待审计代码目录的 `.specdiff/issues.json` |
| OpenCode 运行环境 | 用于加载本作品的命令、Agent、Skill 和工具 |

## 3. 执行工作流

### Step 1：进入作品运行目录

```bash
cd work
```

本步骤进入随作品提交的可运行交付件目录。该目录包含 OpenCode 命令、Agent、工具和 SpecDiff runtime。

预期状态：

```text
当前目录包含 .opencode/、specdiff/、skills/ 和 self_check.py
```

### Step 2：启动 OpenCode

```bash
opencode
```

本步骤启动 OpenCode，使其加载 `work/.opencode/` 中的命令、Agent 和工具。

预期状态：

```text
OpenCode 可识别 /spec-audit 命令
```

### Step 3：运行一致性检视

在 OpenCode 中执行：

```text
/spec-audit <待审计代码目录> <规范或设计文档路径> <输出issues.json路径>
```

执行过程中，工具会自动完成：

```text
读取规范/设计文档
构建 Requirement Packs
为待审计代码目录建立 Code Facts 索引
规划 Batch 审计任务
调用 Code Investigator 检索代码证据
提交结构化调查结果
组装 issues.json 和 SARIF
```

预期输出：

```text
<输出issues.json路径>
<待审计代码目录>/.specdiff/issues.sarif
<待审计代码目录>/.specdiff/audit/
```

### Step 4：读取结果

主结果文件为执行命令中传入的 `issues.json` 路径。其顶层结构为：

```json
{
  "issues": [
    {
      "id": "ISSUE-001",
      "title": "问题标题",
      "rfc_reference": "规范引用",
      "violation_level": "MUST/SHOULD/MAY",
      "file": "相关代码文件",
      "line": 1,
      "evidence": {
        "code_snippet": "代码证据摘录",
        "rfc_requirement": "规范要求摘录"
      }
    }
  ]
}
```

## 4. 产物清单

| 产物 | 位置 | 格式 | 用途 |
|------|------|------|------|
| 作品运行目录 | `work/` | 目录 | 存放 OpenCode 命令、Agent、工具和 SpecDiff runtime |
| Skill 入口 | `work/skills/spec-code-consistency/SKILL.md` | Markdown | 描述一致性检视方法和证据要求 |
| OpenCode 命令 | `work/.opencode/commands/spec-audit.md` | Markdown | 提供 `/spec-audit` 运行入口 |
| OpenCode Agent | `work/.opencode/agents/` | Markdown | 编排审计流程和代码调查 |
| OpenCode 工具 | `work/.opencode/tools/` | TypeScript | 调用 SpecDiff runtime、检索代码、提交结果 |
| SpecDiff runtime | `work/specdiff/` | Python 包 | 负责需求解析、代码索引、状态管理和结果组装 |
| Runtime 副本 | `work/.opencode/specdiff-runtime/specdiff/` | Python 包 | 供 OpenCode 工具稳定导入 |
| 主报告 | `<输出issues.json路径>` | JSON | 记录发现的不一致问题 |
| SARIF 报告 | `<待审计代码目录>/.specdiff/issues.sarif` | SARIF | 供支持 SARIF 的工具读取 |
| 审计过程文件 | `<待审计代码目录>/.specdiff/audit/` | JSON/JSONL/SQLite | 保存需求、Batch、查询、证据和代码索引 |
| 自验证摘要 | `result/output.md` | Markdown | 记录作品自检输出 |
| 交互记录 | `logs/interaction.md` | Markdown | 记录人工交互情况 |
| 过程日志 | `logs/trace/` | 目录 | 存放自检和运行过程记录 |

