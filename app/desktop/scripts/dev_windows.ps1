$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
$AppDir = Join-Path $RootDir "app/desktop"
$UiDir = Join-Path $AppDir "ui"
$TauriDir = Join-Path $AppDir "tauri"
$TauriSidecarDir = Join-Path $TauriDir "sidecar"
$EnvName = "sage-desktop-env"
$Mode = "debug"

function Init-Conda {
  if ($env:CONDA_DEFAULT_ENV -eq $EnvName) {
    return
  }

  $Candidates = @()
  if ($env:CONDA_EXE) { $Candidates += $env:CONDA_EXE }
  $Candidates += @(
    (Join-Path $env:USERPROFILE "miniconda3/Scripts/conda.exe"),
    (Join-Path $env:USERPROFILE "anaconda3/Scripts/conda.exe"),
    "C:/ProgramData/miniconda3/Scripts/conda.exe",
    "C:/ProgramData/anaconda3/Scripts/conda.exe"
  )

  $CondaExe = $null
  foreach ($candidate in $Candidates) {
    if ($candidate -and (Test-Path $candidate)) {
      $CondaExe = $candidate
      break
    }
  }

  if (-not $CondaExe) {
    throw "未找到 Conda。请安装 Miniconda 或 Anaconda。"
  }

  (& $CondaExe "shell.powershell" "hook") | Out-String | Invoke-Expression
  conda activate $EnvName
}

function Install-PythonDeps {
  $reqFile = Join-Path $AppDir "core/requirements.txt"
  $indexUrl = if ($env:PIP_INDEX_URL) { $env:PIP_INDEX_URL } else { "https://pypi.tuna.tsinghua.edu.cn/simple" }
  pip install -r $reqFile --index-url $indexUrl

  & pyinstaller --version *> $null
  if ($LASTEXITCODE -ne 0) {
    pip install pyinstaller --index-url $indexUrl
  }
}

function Prepare-SidecarResources {
  New-Item -ItemType Directory -Force -Path $TauriSidecarDir | Out-Null

  $skillsLink = Join-Path $TauriSidecarDir "skills"
  $mcpLink = Join-Path $TauriSidecarDir "mcp_servers"
  if (Test-Path $skillsLink) { Remove-Item -Force -Recurse $skillsLink }
  if (Test-Path $mcpLink) { Remove-Item -Force -Recurse $mcpLink }

  $skillsSource = Join-Path $RootDir "app/skills"
  $mcpSource = Join-Path $RootDir "mcp_servers"
  try {
    New-Item -ItemType SymbolicLink -Path $skillsLink -Target $skillsSource | Out-Null
    New-Item -ItemType SymbolicLink -Path $mcpLink -Target $mcpSource | Out-Null
  } catch {
    Copy-Item -Path $skillsSource -Destination $skillsLink -Recurse -Force
    Copy-Item -Path $mcpSource -Destination $mcpLink -Recurse -Force
  }
}

function Ensure-FrontendDeps {
  Push-Location $UiDir
  try {
    npm install
  } finally {
    Pop-Location
  }
}

function Start-TauriDev {
  Push-Location $TauriDir
  try {
    $pythonExec = (Get-Command python).Source
    $env:SAGE_PYTHON = $pythonExec
    $env:PYTHONPATH = if ($env:PYTHONPATH) { "$RootDir;$($env:PYTHONPATH)" } else { $RootDir }

    & cargo tauri --version *> $null
    if ($LASTEXITCODE -ne 0) {
      cargo install tauri-cli --version "^2"
    }

    cargo tauri dev
  } finally {
    Pop-Location
  }
}

Write-Host "======================================"
Write-Host " Sage 桌面开发环境 ($Mode)"
Write-Host " 根目录: $RootDir"
Write-Host "======================================"

Init-Conda
Install-PythonDeps
Prepare-SidecarResources
Ensure-FrontendDeps
Start-TauriDev
