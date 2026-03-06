$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
$AppDir = Join-Path $RootDir "app/desktop"
$UiDir = Join-Path $AppDir "ui"
$TauriDir = Join-Path $AppDir "tauri"
$DistDir = Join-Path $AppDir "dist"
$TauriSidecarDir = Join-Path $TauriDir "sidecar"
$CacheDir = Join-Path $AppDir ".build_cache"
$Mode = if ($args.Count -gt 0) { $args[0] } else { "release" }
$EnvName = "sage-desktop-env"

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null

$arch = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } else { "AMD64" }
if ($arch -eq "ARM64") {
  $Target = "aarch64-pc-windows-msvc"
} else {
  $Target = "x86_64-pc-windows-msvc"
}

function Get-HashValue([string]$Path) {
  if (Test-Path $Path) {
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
  }
  return "unknown"
}

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
  if ($env:SKIP_PIP_INSTALL -eq "true") {
    return
  }

  $reqFile = Join-Path $AppDir "core/requirements.txt"
  $hashFile = Join-Path $CacheDir ".requirements.hash"
  $newHash = Get-HashValue $reqFile
  $oldHash = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw).Trim() } else { "" }

  $envOk = $false
  & pip show requests *> $null
  if ($LASTEXITCODE -eq 0) {
    $envOk = $true
  }

  if ($newHash -eq $oldHash -and $envOk) {
    return
  }

  if (-not $env:PIP_INDEX_URL) {
    $env:PIP_INDEX_URL = "https://pypi.org/simple"
  }

  & pip install --upgrade pip setuptools wheel --index-url $env:PIP_INDEX_URL

  if ($env:CONDA_DEFAULT_ENV -eq $EnvName) {
    conda install -y -c conda-forge llvmlite numba
  }

  & pip install -r $reqFile --index-url $env:PIP_INDEX_URL
  & pip install --force-reinstall --no-binary=chardet,charset-normalizer chardet charset-normalizer --index-url $env:PIP_INDEX_URL

  & pyinstaller --version *> $null
  if ($LASTEXITCODE -ne 0) {
    & pip install pyinstaller --index-url $env:PIP_INDEX_URL
  }

  Set-Content -Path $hashFile -Value $newHash -NoNewline
}

function Build-PythonSidecar {
  if ($Mode -eq "release" -and (Test-Path $DistDir)) {
    Remove-Item -Recurse -Force $DistDir
  }
  New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

  $env:PYINSTALLER_CONFIG_DIR = Join-Path $RootDir ".pyinstaller"
  if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$RootDir;$($env:PYTHONPATH)"
  } else {
    $env:PYTHONPATH = $RootDir
  }

  Push-Location $AppDir
  try {
    $flags = @(
      "--noconfirm",
      "--onedir",
      "--log-level=WARN",
      "--name", "sage-desktop",
      "--hidden-import=aiosqlite",
      "--hidden-import=greenlet",
      "--hidden-import=sqlalchemy.dialects.sqlite.aiosqlite",
      "--exclude-module=tkinter",
      "--exclude-module=unittest",
      "--exclude-module=email.test",
      "--exclude-module=test",
      "--exclude-module=tests",
      "--exclude-module=distutils",
      "--exclude-module=setuptools",
      "--exclude-module=xmlrpc",
      "--exclude-module=IPython",
      "--exclude-module=notebook"
    )
    if ($Mode -eq "release") {
      $flags += "--noupx"
      $flags += "--clean"
    }
    & pyinstaller @flags "entry.py"
  } finally {
    Pop-Location
  }

  $builtSidecarDir = Join-Path $DistDir "sage-desktop"
  if (-not (Test-Path $builtSidecarDir)) {
    throw "未找到 Sidecar 目录: $builtSidecarDir"
  }

  Get-ChildItem -Path $DistDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Get-ChildItem -Path $DistDir -Recurse -Include "*.pyc",".DS_Store" -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

  $targetMcpDir = Join-Path $builtSidecarDir "_internal"
  if (-not (Test-Path $targetMcpDir)) {
    $targetMcpDir = $builtSidecarDir
  }

  Copy-Item -Path (Join-Path $RootDir "mcp_servers") -Destination $targetMcpDir -Recurse -Force
  Copy-Item -Path (Join-Path $RootDir "app/skills") -Destination $targetMcpDir -Recurse -Force

  $copiedMcp = Join-Path $targetMcpDir "mcp_servers"
  $copiedSkills = Join-Path $targetMcpDir "skills"
  if (Test-Path $copiedMcp) {
    Get-ChildItem -Path $copiedMcp -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $copiedMcp -Recurse -Directory -Filter ".git" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $copiedMcp -Recurse -Include ".DS_Store" -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
  }
  if (Test-Path $copiedSkills) {
    Get-ChildItem -Path $copiedSkills -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $copiedSkills -Recurse -Directory -Filter ".git" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $copiedSkills -Recurse -Include ".DS_Store" -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
  }

  if (Test-Path $TauriSidecarDir) {
    Remove-Item -Recurse -Force $TauriSidecarDir
  }
  New-Item -ItemType Directory -Force -Path $TauriSidecarDir | Out-Null
  Copy-Item -Path (Join-Path $builtSidecarDir "*") -Destination $TauriSidecarDir -Recurse -Force

  $exePath = Join-Path $TauriSidecarDir "sage-desktop.exe"
  if (-not (Test-Path $exePath)) {
    throw "未找到 Sidecar 可执行文件: $exePath"
  }
}

function Build-Frontend {
  Push-Location $UiDir
  try {
    $lockFile = Join-Path $UiDir "package-lock.json"
    $hashFile = Join-Path $CacheDir ".package-lock.hash"
    $newHash = Get-HashValue $lockFile
    $oldHash = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw).Trim() } else { "" }

    if ($newHash -ne $oldHash -or -not (Test-Path (Join-Path $UiDir "node_modules"))) {
      npm install
      Set-Content -Path $hashFile -Value $newHash -NoNewline
    }

    npm run build
  } finally {
    Pop-Location
  }
}

function Build-Tauri {
  Push-Location $TauriDir
  try {
    $tauriLocalCmd = Join-Path $UiDir "node_modules/.bin/tauri.cmd"
    if (Test-Path $tauriLocalCmd) {
      if ($Mode -eq "release") {
        & $tauriLocalCmd build --target $Target --bundles nsis,msi
      } else {
        & $tauriLocalCmd build --debug --target $Target
      }
      return
    }

    & cargo tauri --version *> $null
    if ($LASTEXITCODE -eq 0) {
      if ($Mode -eq "release") {
        cargo tauri build --target $Target --bundles nsis,msi
      } else {
        cargo tauri build --debug --target $Target
      }
      return
    }

    npm install -g @tauri-apps/cli
    if ($Mode -eq "release") {
      tauri build --target $Target --bundles nsis,msi
    } else {
      tauri build --debug --target $Target
    }
  } finally {
    Pop-Location
  }
}

Write-Host "======================================"
Write-Host " Sage 桌面构建 ($Mode)"
Write-Host " 根目录: $RootDir"
Write-Host " 输出目录: $DistDir"
Write-Host " 缓存目录: $CacheDir"
Write-Host " 目标平台: $Target"
Write-Host "======================================"

Init-Conda
Install-PythonDeps
Build-PythonSidecar
Build-Frontend
Build-Tauri

Write-Host "======================================"
Write-Host " 构建成功完成"
Write-Host "======================================"
