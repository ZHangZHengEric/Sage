# ===============================
# build_windows.ps1
# Build Sage Desktop for Windows
# ===============================

$ErrorActionPreference = "Stop"

# -------------------------------
# Path Configuration
# -------------------------------
$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
$AppDir = Join-Path $RootDir "app/desktop"
$CoreDir = Join-Path $AppDir "core"
$UiDir = Join-Path $AppDir "ui"
$TauriDir = Join-Path $AppDir "tauri"
$TauriSidecarDir = Join-Path $TauriDir "sidecar"
$TauriBinDir = Join-Path $TauriDir "bin"
$DistDir = Join-Path $AppDir "dist"
$CacheDir = Join-Path $AppDir ".build_cache"
$EnvName = "sage-desktop-env"

$Mode = if ($args.Count -gt 0) { $args[0] } else { "release" }

Write-Host "======================================"
Write-Host " Sage Desktop Build ($Mode)"
Write-Host " Root: $RootDir"
Write-Host " Output: $DistDir"
Write-Host " Cache: $CacheDir"
Write-Host "======================================"

if (-not (Test-Path $CacheDir)) {
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
}

function Get-FileHash256 {
    param([string]$FilePath)
    if (Test-Path $FilePath) {
        $hash = Get-FileHash -Path $FilePath -Algorithm SHA256
        return $hash.Hash
    }
    return "unknown"
}

function Find-CondaExe {
    $paths = @(
        $env:CONDA_EXE,
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe"
    )
    foreach ($p in $paths) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return $null
}

$CondaExe = Find-CondaExe
if (-not $CondaExe) {
    Write-Host "[ERROR] Conda not found. Please install Miniconda or Anaconda." -ForegroundColor Red
    exit 1
}

Write-Host "Found Conda: $CondaExe" -ForegroundColor Green
& $CondaExe shell.powershell hook | Out-String | Invoke-Expression

Write-Host "Activating Conda environment '$EnvName'..." -ForegroundColor Cyan

$CurrentEnv = $env:CONDA_DEFAULT_ENV
if ($CurrentEnv -ne $EnvName) {
    conda activate $EnvName
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to activate Conda environment" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Already in Conda environment '$EnvName'. Skipping activation." -ForegroundColor Green
}

Write-Host "Python: $(python --version)" -ForegroundColor Cyan
Write-Host "Pip: $(pip --version)" -ForegroundColor Cyan

function Install-PythonDeps {
    param($CoreDirParam, $CacheDirParam, $EnvNameParam)

    $ReqFile = Join-Path $CoreDirParam "requirements.txt"
    $HashFile = Join-Path $CacheDirParam ".requirements.hash"
    $NewHash = Get-FileHash256 -FilePath $ReqFile
    if (Test-Path $HashFile) {
        $OldHash = Get-Content $HashFile
    } else {
        $OldHash = ""
    }

    $EnvOk = $false
    $pipList = pip list
    if ($pipList -match "requests") {
        $EnvOk = $true
    }

    if ($NewHash -eq $OldHash -and $EnvOk) {
        Write-Host "Python deps unchanged, skipping install." -ForegroundColor Green
    } else {
        Write-Host "Upgrading build tools..." -ForegroundColor Cyan
        $PipIndexUrl = if ($env:PIP_INDEX_URL) { $env:PIP_INDEX_URL } else { "https://mirrors.aliyun.com/pypi/simple" }
        Write-Host "Using pip index: $PipIndexUrl" -ForegroundColor Cyan

        pip install --upgrade pip setuptools wheel --index-url $PipIndexUrl

        Write-Host "Installing deps..." -ForegroundColor Cyan
        pip install -r $ReqFile --index-url $PipIndexUrl

        Write-Host "Replacing python-magic with python-magic-bin for Windows..." -ForegroundColor Cyan
        pip uninstall -y python-magic
        pip install python-magic-bin --index-url $PipIndexUrl

        Write-Host "Force reinstalling pure Python chardet..." -ForegroundColor Cyan
        pip install --force-reinstall --no-binary=chardet,charset-normalizer chardet charset-normalizer --index-url $PipIndexUrl 
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Falling back to official PyPI for chardet..." -ForegroundColor Yellow
            pip install --force-reinstall --no-binary=chardet,charset-normalizer chardet charset-normalizer --index-url https://pypi.org/simple
        }

        if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
            pip install pyinstaller --index-url $PipIndexUrl
        }

        $NewHash | Out-File -FilePath $HashFile -Encoding UTF8
    }
}

Install-PythonDeps -CoreDirParam $CoreDir -CacheDirParam $CacheDir -EnvNameParam $EnvName

function Build-PythonSidecar {
    param($DistDirParam, $TauriSidecarDirParam, $AppDirParam, $RootDirParam, $ModeParam)

    Write-Host "[Sidecar] Building Python Sidecar..." -ForegroundColor Cyan

    if ($ModeParam -eq "release") {
        if (Test-Path $DistDirParam) {
            Remove-Item -Recurse -Force $DistDirParam
        }
    }
    if (-not (Test-Path $DistDirParam)) {
        New-Item -ItemType Directory -Force -Path $DistDirParam | Out-Null
    }

    $env:PYINSTALLER_CONFIG_DIR = Join-Path $RootDirParam ".pyinstaller"
    $pyPath = "$RootDirParam;$env:PYTHONPATH"
    $env:PYTHONPATH = $pyPath

    Set-Location $AppDirParam

    $PyiFlags = @(
        "--noconfirm",
        "--onedir",
        "--log-level=WARN",
        "--name", "sage-desktop",
        "--windowed",
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

    if ($ModeParam -eq "release") {
        $PyiFlags += "--noupx"
        $PyiFlags += "--clean"
    }

    $entryPath = Join-Path $AppDirParam "entry.py"
    $pyinstallerCmd = "pyinstaller"
    foreach ($flag in $PyiFlags) {
        $pyinstallerCmd += " $flag"
    }
    $pyinstallerCmd += " $entryPath"

    Invoke-Expression $pyinstallerCmd

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] PyInstaller build failed" -ForegroundColor Red
        exit 1
    }

    Write-Host "[Sidecar] Cleaning dist files..." -ForegroundColor Cyan
    Get-ChildItem -Path $DistDirParam -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $DistDirParam -Recurse -File -Filter "*.pyc" | Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $DistDirParam -Recurse -File -Filter ".DS_Store" | Remove-Item -Force -ErrorAction SilentlyContinue

    Write-Host "[Sidecar] Copying mcp_servers to dist..." -ForegroundColor Cyan
    $targetMcpDir = Join-Path $DistDirParam "sage-desktop"
    if (Test-Path (Join-Path $DistDirParam "sage-desktop\_internal")) {
        $targetMcpDir = Join-Path $DistDirParam "sage-desktop\_internal"
    }

    $mcpServersSrc = Join-Path $RootDirParam "mcp_servers"
    if (Test-Path $mcpServersSrc) {
        Copy-Item -Path $mcpServersSrc -Destination $targetMcpDir -Recurse -Force
        $mcpPath = Join-Path $targetMcpDir "mcp_servers"
        Get-ChildItem -Path $mcpPath -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $mcpPath -Recurse -Directory -Filter ".git" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $mcpPath -Recurse -File -Filter ".DS_Store" | Remove-Item -Force -ErrorAction SilentlyContinue
    }

    Write-Host "[Sidecar] Copying skills to dist..." -ForegroundColor Cyan
    $skillsSrc = Join-Path $RootDirParam "app/skills"
    if (Test-Path $skillsSrc) {
        Copy-Item -Path $skillsSrc -Destination $targetMcpDir -Recurse -Force
        $skillsPath = Join-Path $targetMcpDir "skills"
        Get-ChildItem -Path $skillsPath -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $skillsPath -Recurse -Directory -Filter ".git" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $skillsPath -Recurse -File -Filter ".DS_Store" | Remove-Item -Force -ErrorAction SilentlyContinue
    }

    Set-Location $RootDirParam

    Write-Host "[Sidecar] Copying to Tauri Sidecar dir..." -ForegroundColor Cyan
    if (Test-Path $TauriSidecarDirParam) {
        Remove-Item -Recurse -Force $TauriSidecarDirParam
    }
    New-Item -ItemType Directory -Force -Path $TauriSidecarDirParam | Out-Null

    $srcDir = Join-Path $DistDirParam "sage-desktop"
    if (-not (Test-Path $srcDir)) {
        Write-Host "ERROR: Sidecar dir not found: $srcDir" -ForegroundColor Red
        exit 1
    }

    Copy-Item -Path "$srcDir\*" -Destination $TauriSidecarDirParam -Recurse -Force

    $exePath = Join-Path $TauriSidecarDirParam "sage-desktop.exe"
    if (Test-Path $exePath) {
        Write-Host "[Sidecar] Copied to: $TauriSidecarDirParam" -ForegroundColor Green
    }
}

function Build-Frontend {
    param($UiDirParam, $CacheDirParam, $RootDirParam)

    Write-Host "[Frontend] Building frontend..." -ForegroundColor Cyan
    Set-Location $UiDirParam

    $LockFile = Join-Path $UiDirParam "package-lock.json"
    $HashFile = Join-Path $CacheDirParam ".package-lock.hash"
    $NewHash = Get-FileHash256 -FilePath $LockFile
    if (Test-Path $HashFile) {
        $OldHash = Get-Content $HashFile
    } else {
        $OldHash = ""
    }

    if ($NewHash -eq $OldHash -and (Test-Path "node_modules")) {
        Write-Host "[Frontend] Deps unchanged, skipping npm install." -ForegroundColor Green
    } else {
        npm install
        $NewHash | Out-File -FilePath $HashFile -Encoding UTF8
    }

    npm run build
    Set-Location $RootDirParam
}

Write-Host ">>> Starting build tasks..." -ForegroundColor Cyan

Build-PythonSidecar -DistDirParam $DistDir -TauriSidecarDirParam $TauriSidecarDir -AppDirParam $AppDir -RootDirParam $RootDir -ModeParam $Mode
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Sidecar build failed!" -ForegroundColor Red
    exit 1
}

Build-Frontend -UiDirParam $UiDir -CacheDirParam $CacheDir -RootDirParam $RootDir
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Frontend build failed!" -ForegroundColor Red
    exit 1
}

Write-Host ">>> Build completed." -ForegroundColor Green

Set-Location $RootDir

Write-Host "Building Tauri Windows executable..." -ForegroundColor Cyan
Set-Location $TauriDir

$TauriCmd = $null
$TauriArgs = $null
$LocalTauri = Join-Path $UiDir "node_modules\.bin\tauri"
$LocalTauriCmd = Join-Path $UiDir "node_modules\.bin\tauri.cmd"
if (Test-Path $LocalTauriCmd) {
    Write-Host "Using local Tauri CLI (.cmd)..." -ForegroundColor Cyan
    $TauriCmd = $LocalTauriCmd
    $TauriArgs = if ($Mode -eq "release") { @("build") } else { @("build", "--debug") }
} elseif (Test-Path $LocalTauri) {
    Write-Host "Using local Tauri CLI (via npx)..." -ForegroundColor Cyan
    $TauriCmd = "npx"
    $TauriArgs = if ($Mode -eq "release") { @("tauri", "build") } else { @("tauri", "build", "--debug") }
} elseif (Get-Command cargo-tauri -ErrorAction SilentlyContinue) {
    Write-Host "Using Cargo Tauri CLI..." -ForegroundColor Cyan
    $TauriCmd = "cargo"
    $TauriArgs = if ($Mode -eq "release") { @("tauri", "build") } else { @("tauri", "build", "--debug") }
} else {
    Write-Host "Installing Tauri CLI (via npm)..." -ForegroundColor Cyan
    npm install -g @tauri-apps/cli
    $TauriCmd = "tauri"
    $TauriArgs = if ($Mode -eq "release") { @("build") } else { @("build", "--debug") }
}

Write-Host "Tauri CLI: $TauriCmd" -ForegroundColor Cyan
$env:CI = "true"
$env:CARGO_TERM_COLOR = "never"
# Skip signature for updater artifacts as keys are not provided
# $env:TAURI_SKIP_SIGNATURE = "true"

Write-Host "Building Tauri application (this may take a while)..." -ForegroundColor Cyan

$Process = Start-Process -FilePath $TauriCmd -ArgumentList $TauriArgs -NoNewWindow -Wait -PassThru -WorkingDirectory $TauriDir
if ($Process.ExitCode -ne 0) {
  Write-Host "[ERROR] Tauri build failed" -ForegroundColor Red
  exit $Process.ExitCode
}
 
Write-Host "======================================"
Write-Host " Build completed successfully!"
Write-Host "======================================"
