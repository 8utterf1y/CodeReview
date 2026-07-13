# SpecDiff Batch Windows Deployment

This folder is a Windows-oriented copy of the current batch-mode `work/`.

## Prerequisites

- Windows 10/11
- Python 3 available as `python`
- OpenCode installed

If Python is installed under another command, set:

```powershell
$env:PYTHON = "C:\Path\To\python.exe"
```

## Install Into A Repository

From this `workbatchwin` folder:

```powershell
.\install_opencode_interactive.ps1 -Target C:\path\to\repo -Force
```

Then start OpenCode from the target repository:

```powershell
cd C:\path\to\repo
opencode
```

Run:

```text
/spec-audit C:\path\to\docs.md .specdiff\issues.json
```

## Notes

- This version uses Audit Batches: Pack remains the result/coverage unit, Batch is only the Agent dispatch unit.
- OpenCode tools use `python` on Windows and `python3` elsewhere.
- `PYTHONPATH` uses the platform path delimiter automatically.
- The runtime is copied into `.opencode\specdiff-runtime`.
