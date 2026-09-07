$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$env:UV_CACHE_DIR = "$ProjectRoot\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$ProjectRoot\.uv-python"

# uv's standalone installer uses this directory by default on Windows. Add it
# without assuming a particular Windows account name, then resolve the command.
$UvBinDir = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path -LiteralPath $UvBinDir) {
    $env:Path = "$UvBinDir;$env:Path"
}

$UvCommand = Get-Command "uv" -ErrorAction SilentlyContinue
if (-not $UvCommand) {
    $UvCandidates = @(
        (Join-Path $UvBinDir "uv.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\uv.exe")
    )
    $UvExecutable = $UvCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1

    if (-not $UvExecutable) {
        $WingetPackages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
        $UvExecutable = Get-ChildItem -Path $WingetPackages -Filter "uv.exe" -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '[\\/]astral-sh\.uv_' } |
            Select-Object -First 1 -ExpandProperty FullName
    }

    if ($UvExecutable) {
        $UvCommand = Get-Command $UvExecutable
    }
}

if (-not $UvCommand) {
    throw "uv was not found. Install it with 'winget install --id astral-sh.uv', then run this script again."
}

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path -LiteralPath $EnvFile) {
    foreach ($Line in Get-Content -LiteralPath $EnvFile) {
        $TrimmedLine = $Line.Trim()
        if (-not $TrimmedLine -or $TrimmedLine.StartsWith("#")) {
            continue
        }

        $Parts = $TrimmedLine.Split("=", 2)
        if ($Parts.Count -ne 2) {
            continue
        }

        $Name = $Parts[0].Trim()
        $Value = $Parts[1].Trim().Trim('"').Trim("'")
        if ($Name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
        }
    }
}

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

# Windows PowerShell converts output written by native programs to stderr into
# PowerShell error records. With ErrorActionPreference set to Stop, routine uv
# status messages (for example, "Using CPython ...") would terminate this
# script even though uv itself had not failed.
$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $UvCommand.Source run streamlit run app.py `
        --server.address 0.0.0.0 `
        --server.port 8501 `
        --server.headless true `
        --browser.gatherUsageStats false *>> $ServerLogFile
    $UvExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

if ($UvExitCode -ne 0) {
    throw "Finance Dashboard exited with code $UvExitCode. See $ServerLogFile for details."
}
