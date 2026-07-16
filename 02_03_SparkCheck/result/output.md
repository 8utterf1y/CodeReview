# 自验证输出记录

## 作品信息

```text
作品目录：02_03_SparkCheck
题目：题目 3，识别代码实现和设计文档中的不一致问题
运行方式：OpenCode /spec-audit
```

## 自检命令

```bash
cd 02_03_SparkCheck/work
python self_check.py
```

## 自检结果

```text
self-check passed: required files present and runtime imports
```

## 平台运行命令

Windows 示例：

```text
/spec-audit C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack\.specdiff\issues.json
```

Linux 示例：

```text
/spec-audit /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/Difference/benchmark.md /app/code/judge-assets/01_03_ai_implementation_design_difference_detection/code/f-stack/.specdiff/issues.json
```

## 预期输出文件

```text
code/f-stack/.specdiff/issues.json
code/f-stack/.specdiff/issues.sarif
code/f-stack/.specdiff/audit/
```

## 输出格式

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

