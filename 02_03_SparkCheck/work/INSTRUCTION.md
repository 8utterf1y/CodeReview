# SpecDiff Work 目录运行说明

本目录是作品实际运行目录。平台或评测 Agent 应在本目录启动 OpenCode。

## 必需环境

```text
Python 3.9+
OpenCode
```

Windows 下 Python 命令使用：

```text
python
```

## 快速自检

```bash
python self_check.py
```

成功输出：

```text
self-check passed: required files present and runtime imports
```

## 审计命令

在本目录启动 OpenCode：

```bash
opencode
```

然后执行：

```text
/spec-audit <repo> <docs> <out>
```

参数：

```text
repo = 被审计代码仓目录
docs = 设计文档、需求 JSON 或 RFC inventory/benchmark.md
out  = 输出 issues.json 路径
```

示例：

```text
/spec-audit C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack\.specdiff\issues.json
```

## 执行约束

```text
1. 不要从被审计代码仓目录启动 OpenCode；
2. 必须从本 work 目录启动；
3. 被审计代码仓通过 /spec-audit 的 repo 参数传入；
4. 不需要手动设置 PYTHONPATH，OpenCode tool 会自动定位 .opencode/specdiff-runtime；
5. 不需要安装 rg、CodeQL、Joern、Semgrep 或向量数据库。
```

## 输出

主输出：

```text
<out>
```

格式：

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

附加输出：

```text
<repo>/.specdiff/issues.sarif
<repo>/.specdiff/audit/
```
