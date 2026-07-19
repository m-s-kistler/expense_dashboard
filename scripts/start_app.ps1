$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$env:Path = "C:\Users\mskis\.local\bin;$env:Path"
$env:UV_CACHE_DIR = "$ProjectRoot\.uv-cache"

$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LauncherLogFile = Join-Path $LogDir "expense_dashboard_$Timestamp`_launcher.log"
$ServerLogFile = Join-Path $LogDir "expense_dashboard_$Timestamp`_server.log"
$AppLogFile = Join-Path $LogDir "expense_dashboard_$Timestamp`_app.log"
$env:EXPENSE_DASHBOARD_LOG_FILE = $AppLogFile

"$(Get-Date -Format o) INFO [launcher] Starting Finance Dashboard from $ProjectRoot" |
    Out-File -FilePath $LauncherLogFile -Encoding utf8
"$(Get-Date -Format o) INFO [launcher] App log: $AppLogFile" |
    Out-File -FilePath $LauncherLogFile -Encoding utf8 -Append
"$(Get-Date -Format o) INFO [launcher] Server log: $ServerLogFile" |
    Out-File -FilePath $LauncherLogFile -Encoding utf8 -Append

& uv run streamlit run app.py `
    --server.address 0.0.0.0 `
    --server.port 8501 `
    --server.headless true `
    --browser.gatherUsageStats false *>> $ServerLogFile
