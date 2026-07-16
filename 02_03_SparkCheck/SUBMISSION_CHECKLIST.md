# 提交资料清单

作品名：

```text
02_03_SparkCheck
```

提交压缩包：

```text
02_03_SparkCheck.zip
```

## 1. 根目录

```text
02_03_SparkCheck/
  INSTRUCTION.md
  work/
  result/
  logs/
  TECHNICAL_REPORT.md
  SUBMISSION_CHECKLIST.md
```

## 2. 必选交付件

```text
INSTRUCTION.md                 作品运行入口
work/                          可运行交付件目录
result/output.md               自验证输出记录
logs/interaction.md            人工交互记录
logs/trace/                    推理/自检记录
```

## 3. Work 目录

```text
work/
  INSTRUCTION.md
  self_check.py
  .opencode/
  specdiff/
  specdiff-vendor-slim/
  skills/spec-code-consistency/SKILL.md
```

## 4. OpenCode 组件

```text
work/.opencode/commands/spec-audit.md
work/.opencode/commands/prepare-rfcs.md
work/.opencode/agents/spec-compliance-orchestrator.md
work/.opencode/agents/code-investigator.md
work/.opencode/agents/evidence-reviewer.md
work/.opencode/tools/*.ts
work/.opencode/specdiff-runtime/specdiff/
work/.opencode/skills/spec-code-consistency/SKILL.md
```

## 5. Runtime

```text
work/specdiff/
  audit_runtime.py
  tool_api.py
  rfc_prepare.py
  rfc_packs.py
  repository_index.py
  codefacts.py
  spec_loader.py
  coverage_gate.py
  report.py
```

## 6. 运行命令

进入：

```bash
cd 02_03_SparkCheck/work
opencode
```

OpenCode 内执行：

```text
/spec-audit <repo> <docs> <out>
```

其中：

```text
repo = 被审计代码仓
docs = 设计文档、需求 JSON 或 benchmark.md
out  = 输出 issues.json
```

## 7. 输出

```text
<out>
<repo>/.specdiff/issues.sarif
<repo>/.specdiff/audit/
```

`<out>` 顶层字段：

```json
{
  "issues": []
}
```

## 8. 自检

```bash
cd 02_03_SparkCheck/work
python self_check.py
```

期望输出：

```text
self-check passed: required files present and runtime imports
```

## 9. 不包含内容

提交包不包含：

```text
完整 f-stack 仓库
评测 Difference 目录
运行残留 .specdiff
单元测试目录 tests
临时测试数据 testdata
macOS __MACOSX 元数据
```
