# SpecDiff 参赛作品执行说明书（Windows / OpenCode 版）

本目录是题目 3「识别代码实现和设计文档中的不一致问题」的 Windows 版提交目录。提交到评测平台时，请将本目录内容作为 `work/` 根目录提交。

## 1. 环境准备

### 1.1 必需环境

```text
Windows 10/11
Python 3.9+
OpenCode
```

Python 命令固定使用 `python`，请确认以下命令可执行：

```powershell
python
```

运行所需的 SpecDiff runtime、OpenCode tools、agents、skill 和精简 vendor 依赖均随 `work/` 提交。

### 1.2 SpecDiff 运行时路径要求

SpecDiff 工具运行时基于当前 OpenCode 项目根目录定位：

```text
<work>\.opencode\specdiff-runtime
```

被审计代码仓通过 `/spec-audit` 的 `repo` 参数传入；工具启动时会使用 OpenCode 提供的项目根目录设置 `PYTHONPATH`，然后执行：

```text
python -m specdiff.tool_api
```

部署后可在 `work` 目录中验证：

```powershell
cd C:\judge-assets\01_03_ai_implementation_design_difference_detection\work
$env:PYTHONPATH = ".opencode\specdiff-runtime"
python -m specdiff.tool_api extract-requirements --docs C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md
```

### 1.3 项目目录

假设平台资源目录为：

```text
C:\judge-assets\01_03_ai_implementation_design_difference_detection
```

其中：

```text
code\f-stack
Difference\benchmark.md
work
```

进入提交目录并启动 OpenCode：

```powershell
cd C:\judge-assets\01_03_ai_implementation_design_difference_detection\work
opencode
```

提交目录包含：

```text
.opencode\commands\
.opencode\agents\
.opencode\tools\
.opencode\skills\spec-code-consistency\
.opencode\specdiff-runtime\
```

## 2. 执行流程

进入提交目录：

```powershell
cd C:\judge-assets\01_03_ai_implementation_design_difference_detection\work
```

启动 OpenCode：

```powershell
opencode
```

在 OpenCode 中执行：

```text
/spec-audit C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack\.specdiff\issues.json
```

参数说明：

```text
第 1 个参数 repo：被审计代码仓路径，本题为 code\f-stack
第 2 个参数 docs：设计文档/RFC 清单路径，本题为 Difference\benchmark.md
第 3 个参数 out：最终 JSON 输出路径，建议写入 code\f-stack\.specdiff\issues.json
当前 OpenCode 工作目录：提交目录 work
```

如果运行环境使用平台 Linux 路径，等价命令为：

```bash
cd /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/work
opencode
```

OpenCode 内执行：

```text
/spec-audit /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/Difference/benchmark.md /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack/.specdiff/issues.json
```

## 3. 执行完成判定

执行完成条件：

```text
audit_finish 成功返回
并生成 .specdiff\issues.json
```

同时会生成：

```text
.specdiff\issues.sarif
.specdiff\audit\requirements.json
.specdiff\audit\batches.json
.specdiff\audit\queries.jsonl
.specdiff\audit\evidence.jsonl
.specdiff\audit\investigations.json
```

如果单个 Batch 未调查完成，Runtime 会将该 Batch 内未提交的 Pack 收敛为 `unknown`，继续后续流程；单个 Pack 或单个 Agent 调查失败不会阻塞整个审计。

## 4. 结果获取方式

主结果文件：

```text
code\f-stack\.specdiff\issues.json
```

SARIF 文件：

```text
code\f-stack\.specdiff\issues.sarif
```

`issues.json` 中核心字段：

```json
{
  "issues": [
    {
      "id": "ISSUE-001",
      "title": "不一致问题标题",
      "requirement_id": "PACK-...",
      "severity": "high",
      "confidence": 0.9,
      "match_type": "missing_in_code",
      "spec_evidence": [
        {
          "document": "RFC 4861",
          "section": "7.2.8",
          "quote": "规范原文摘录"
        }
      ],
      "code_evidence": [
        {
          "path": "freebsd/netinet6/nd6_nbr.c",
          "start_line": 650,
          "end_line": 651,
          "quote": "代码证据摘录"
        }
      ],
      "description": "代码实现与设计/RFC 要求的不一致说明"
    }
  ]
}
```

## 5. 工具工作方式

本作品的主执行路径是 OpenCode Agent/Skill/Tool 组合，审计流程由程序状态机控制：

```text
benchmark.md / requirements JSON
  -> RFC 正文缓存与 Requirement Pack 构建
  -> 代码仓 Code Facts SQLite 索引
  -> Batch Planner 生成审计 Batch
  -> Code Investigator 调查每个 Batch
  -> submit_batch_results 逐 Pack 提交结构化结果
  -> audit_finish 组装 issues.json / SARIF
```

Requirement Pack 是最终覆盖率和结果单位；Batch 只是 Agent 调查调度单位。Runtime 负责状态、证据 ID、schema 校验、失败隔离和最终文件生成，Agent 只负责在限定 Batch 内查找证据并提交结构化结果。

## 6. 提交目录要求

提交时目录至少包含：

```text
work\
  INSTRUCTION.md
  技术报告.md
  提交资料清单.md
  .opencode\
  skills\spec-code-consistency\SKILL.md
  specdiff\
  specdiff-vendor-slim\
```

其中 `skills\spec-code-consistency\SKILL.md` 满足平台对 Skill 路径的要求。
