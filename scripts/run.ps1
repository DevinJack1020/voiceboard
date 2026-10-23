$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 D 盘项目虚拟环境。请先运行：python -m venv .venv"
}

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path -LiteralPath $EnvFile) {
    foreach ($Line in Get-Content -LiteralPath $EnvFile) {
        $Trimmed = $Line.Trim()
        if (-not $Trimmed -or $Trimmed.StartsWith("#")) { continue }
        $Parts = $Trimmed -split "=", 2
        if ($Parts.Count -eq 2 -and $Parts[0] -match "^[A-Z][A-Z0-9_]*$") {
            [Environment]::SetEnvironmentVariable($Parts[0], $Parts[1], "Process")
        }
    }
}

& $Python -m streamlit run (Join-Path $ProjectRoot "app.py")

