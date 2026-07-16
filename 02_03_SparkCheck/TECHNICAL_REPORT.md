# SpecDiff 技术报告

## 1. 技术方案概述

SpecDiff 是一个面向代码实现与设计文档/RFC 规范一致性检视的 OpenCode 工具集。系统将输入文档转换为可追溯的 Requirement Packs，结合目标仓库的代码事实库生成审计任务，由 Agent 在受控工具协议下完成证据检索和结果提交，最终由程序组装 `issues.json` 和 SARIF 报告。

整体流程：

```text
代码仓 + 设计文档/RFC 清单
  -> 需求/RFC 解析
  -> Requirement Pack 构建
  -> Code Facts 索引
  -> Batch Planner
  -> Code Investigator
  -> 结构化结果提交
  -> 结果校验与组装
  -> issues.json + issues.sarif
```

Runtime 负责审计状态、证据编号、schema 校验、失败隔离和最终报告生成；Agent 负责在限定 Batch 内查找代码证据并提交结构化结论。

## 2. 需求建模

输入文档支持：

```text
显式 requirements JSON
RFC 清单 / Markdown 规范文档
```

对于 RFC 清单，系统读取 RFC 编号，获取 RFC 正文，抽取规范性段落和必要上下文，生成 bounded Requirement Packs。Requirement Pack 是最终覆盖率和结果单位。

Requirement Pack 主要字段：

```text
id
document
section
quote
normalized
keywords
seed_clause_ids
clause_ids
clauses
normative_strength
```

这些字段用于保持规范来源、章节位置、原文证据和代码调查结果之间的可追溯关系。

## 3. 代码事实库

审计开始后，系统在目标仓库下生成代码索引：

```text
.specdiff/audit/code-index/
  repository.json
  files.jsonl
  symbols.jsonl
  references.jsonl
  calls.jsonl
  components.json
  build_graph.json
  tool_coverage.json
  codefacts.sqlite
```

`code_search` 基于该索引提供以下检索能力：

```text
repo_map
component
symbol
references
callers
callees
source
concept
```

这些能力用于帮助 Agent 从仓库结构、组件、符号、源码片段和调用关系等角度定位实现证据。

## 4. Batch Planner

Batch Planner 将多个相关 Requirement Packs 组合成一个调查 Batch，以减少重复检索并复用同一代码上下文。

规划过程：

```text
Requirement Pack
  -> 代码亲和性分析
  -> topic 分组
  -> 相似 topic 合并
  -> 超大 Batch 拆分
  -> Audit Batches
```

关键参数：

```python
TARGET_BATCHES = 24
HARD_MAX_BATCHES = 30
MIN_TOPIC_MERGE_SCORE = 6.0
MAX_BATCH_PACKET_PACKS = 12
MAX_BATCH_PACKET_CLAUSES = 160
MAX_BATCH_QUERIES = 120
MAX_BATCH_TEXT_QUERIES = 60
```

Batch 只作为 Agent 调查调度单位；Pack 仍然是最终结果、coverage 和输出 issue 的单位。

## 5. Agent 调查协议

OpenCode Orchestrator 按 Runtime 返回的动作执行：

```text
audit_start
audit_next
Code-Investigator
submit_batch_results
audit_next
...
audit_finish
```

Code-Investigator 收到 Batch 后，先进行共享实现发现，再使用 `code_search` 定位源码证据。`code_search` 在 Batch 模式下自动绑定当前 active batch，Agent 不需要选择 scope ID。

`submit_batch_results` 按单条 result 校验：

```text
合法 result -> 持久化
非法 result -> rejected_results
其他 result 不受影响
```

若未提供 `specClauseIds`，Runtime 自动使用 Pack 的 `seed_clause_ids` 或 `clause_ids` 作为规范出处。

## 6. 失败隔离与最终组装

审计过程中，单个 Pack 或 Batch 未能完成时，Runtime 会记录为 `unknown` 并继续后续 Batch。最终 `audit_finish` 汇总全部 Pack 状态并输出：

```text
.specdiff/issues.json
.specdiff/issues.sarif
```

进入 `issues` 的结果包含：

```text
问题标题
严重度
置信度
不一致类型
规范证据
代码证据
涉及文件和行号
```

## 7. 工具部署及使用手册

Windows 运行：

```powershell
cd C:\judge-assets\01_03_ai_implementation_design_difference_detection\work
opencode
```

OpenCode 内执行：

```text
/spec-audit C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack\.specdiff\issues.json
```

结果文件：

```text
C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack\.specdiff\issues.json
```

## 8. 运行时路径

OpenCode 工具根据当前项目根目录定位 runtime：

```text
<work>\.opencode\specdiff-runtime
```

部署验证：

```powershell
cd C:\judge-assets\01_03_ai_implementation_design_difference_detection\work
$env:PYTHONPATH = ".opencode\specdiff-runtime"
python -m specdiff.tool_api extract-requirements --docs C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md
```

## 9. 基准测试效果验证

题目基准包含以下不一致类型：

```text
ND option hard limit
Proxy NA random delay missing
Proxy NA unsolicited advertisement missing
IPv6 fragment extension-header chain walking
DHCPv6 missing implementation
MLD multicast receive path issue
```

系统输出的 issue 应包含：

```text
规范证据：RFC/设计文档章节和原文
代码证据：文件路径、行号、源码片段
问题分类：missing_in_code / code_weaker_than_spec / partial_match 等
严重度与置信度
```

验收目标：

```text
识别 issues 数量 >= 4
误报率 <= 50%
检视时长 <= 6 小时
```
