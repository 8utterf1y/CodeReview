# SpecDiff Windows 快速部署说明

本目录是 Windows/OpenCode 版提交包。提交到评测平台时，将本目录内容作为 `work/` 目录。

## 1. 前置条件

```text
Windows 10/11
Python 3.9+，命令为 python
OpenCode
```

请确认 `python` 已在 PATH 中可直接执行。

## 2. 启动 OpenCode

```powershell
cd C:\judge-assets\01_03_ai_implementation_design_difference_detection\work
opencode
```

SpecDiff runtime、tools、agents、commands 和 skill 均位于提交目录：

```text
work\.opencode\
```

## 3. 运行审计

OpenCode 内输入：

```text
/spec-audit C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack C:\judge-assets\01_03_ai_implementation_design_difference_detection\Difference\benchmark.md C:\judge-assets\01_03_ai_implementation_design_difference_detection\code\f-stack\.specdiff\issues.json
```

## 4. 输出

```text
code\f-stack\.specdiff\issues.json
code\f-stack\.specdiff\issues.sarif
```

## 5. 注意

- Batch 是 Agent 调查单位，Pack 是最终结果单位。
- `code_search` 在 Batch 模式下自动绑定 active batch，不需要手工填写 requirementId。
- Windows tools 固定使用 `python`，并使用 `;` 作为 `PYTHONPATH` 分隔符。
- 重新审计同一个仓库前，建议清理 `work\.specdiff\audit` 工作目录后再运行。
