$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 D 盘项目虚拟环境。请先运行：python -m venv .venv"
}

& $Python -m streamlit run (Join-Path $ProjectRoot "app.py")

