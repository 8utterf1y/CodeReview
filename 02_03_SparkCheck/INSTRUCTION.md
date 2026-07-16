# SpecDiff 作品运行指令

本文件是平台加载作品后的唯一入口。请严格按以下步骤运行，不要修改 `work/` 内文件，不要把被审计仓库复制到 `work/` 内。

## 1. 作品目录

解压后目录结构应为：

```text
02_03_SparkCheck/
  INSTRUCTION.md
  work/
  result/
  logs/
```

所有工具、Agent、Skill 和运行时都在：

```text
02_03_SparkCheck/work
```

## 2. 输入定位

评测平台应提供：

```text
repo = 被审计代码仓目录，例如 code/f-stack
docs = 设计文档或 benchmark.md，例如 Difference/benchmark.md
out  = 输出文件路径，建议为 <repo>/.specdiff/issues.json
```

如果平台没有显式给出 `out`，使用：

```text
<repo>/.specdiff/issues.json
```

## 3. 执行步骤

进入作品运行目录：

```bash
cd 02_03_SparkCheck/work
```

启动 OpenCode：

```bash
opencode
```

在 OpenCode 中执行：

```text
/spec-audit <repo> <docs> <out>
```

Windows 示例：

```text
/spec-audit C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack\.specdiff\issues.json
```

Linux 示例：

```text
/spec-audit /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/Difference/benchmark.md /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack/.specdiff/issues.json
```

## 4. 成功判定

运行成功必须满足：

```text
1. OpenCode workflow 执行到 audit_finish；
2. <out> 文件存在；
3. <out> 是 JSON；
4. <out> 顶层包含 issues 数组。
```

可用以下命令验证：

```bash
python -m json.tool <out>
```

## 5. 输出格式

`<out>` 使用题目要求格式：

```json
{
  "issues": [
    {
      "id": "ISSUE-001",
      "title": "问题标题",
      "rfc_reference": "RFC 4861 §7.2.8",
      "violation_level": "SHOULD",
      "file": "freebsd/netinet6/nd6_nbr.c",
      "line": 650,
      "evidence": {
        "code_snippet": "代码证据摘录",
        "rfc_requirement": "规范要求摘录"
      }
    }
  ]
}
```

同时会在 `<repo>/.specdiff/` 下生成 SARIF 和审计过程文件。

## 6. 自检

如需先验证作品运行时是否可导入，在 `work/` 目录执行：

```bash
python self_check.py
```

成功输出：

```text
self-check passed: required files present and runtime imports
```
