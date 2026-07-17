param(
    [string]$SourceCommit = $(git rev-parse HEAD),
    [string]$Output = "evidence\v2-model-evaluation-dashboard.json"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python (Join-Path $Root "scripts\verify_v2_model_evaluation.py") --source-commit $SourceCommit --output (Join-Path $Root $Output)
exit $LASTEXITCODE
