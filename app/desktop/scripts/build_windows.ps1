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
$TauriNodeSidecarDir = Join-Path $TauriSidecarDir "node"
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
        "$env:USERPROFILE\AppData\Local\miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\AppData\Local\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\Anaconda3\Scripts\conda.exe"
    )
    foreach ($p in $paths) {
        if ($p -and (Test-Path $p)) { return $p }
    }

    $condaCmd = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($condaCmd -and (Test-Path $condaCmd.Source)) {
        return $condaCmd.Source
    }

    return $null
}

function Resolve-CondaEnvPython {
    param(
        [string]$CondaExe,
        [string]$EnvName,
        [string]$CondaBase
    )

    $envListLines = & $CondaExe env list 2>$null
    foreach ($line in $envListLines) {
        $trimmed = $line.Trim()
        if ($trimmed -match '^#|^\s*$') { continue }
        $parts = $trimmed -split '\s+', 3
        if ($parts.Count -ge 2 -and $parts[0] -eq $EnvName) {
            $envPath = $parts[-1]
            $pythonExe = Join-Path $envPath "python.exe"
            if (Test-Path $pythonExe) { return $pythonExe }
        }
    }

    $defaultPython = Join-Path $CondaBase "envs\$EnvName\python.exe"
    if (Test-Path $defaultPython) { return $defaultPython }

    try {
        $resolved = (& $CondaExe run -n $EnvName python -c "import sys; print(sys.executable)" 2>$null).Trim()
        if ($resolved -and (Test-Path $resolved)) { return $resolved }
    } catch {}

    return $null
}

function Ensure-PythonPackagingTools {
    param(
        [string]$CondaExe,
        [string]$EnvName,
        [string]$SagePythonParam
    )

    & $SagePythonParam -m pip --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "Pip is missing in Conda environment '$EnvName'. Installing packaging tools..." -ForegroundColor Yellow
    & $CondaExe install -n $EnvName -y pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install pip/setuptools/wheel into Conda environment '$EnvName'." -ForegroundColor Red
        exit 1
    }

    & $SagePythonParam -m pip --version
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] pip is still unavailable in Conda environment '$EnvName'." -ForegroundColor Red
        exit 1
    }
}

function Sync-CondaRuntimeToSidecar {
    param(
        [string]$SagePythonParam,
        [string]$InternalDir
    )

    if (-not (Test-Path $InternalDir)) {
        Write-Host "[Sidecar] WARN: _internal dir not found: $InternalDir" -ForegroundColor Yellow
        return
    }

    $CondaEnvRoot = Split-Path -Parent $SagePythonParam
    $CondaBin = Join-Path $CondaEnvRoot "Library\bin"
    $CondaDlls = Join-Path $CondaEnvRoot "DLLs"

    if (Test-Path $CondaBin) {
        $RuntimeDlls = Get-ChildItem -Path $CondaBin -Filter "*.dll" -File
        Write-Host "[Sidecar] Syncing $($RuntimeDlls.Count) Conda runtime DLL(s) from $CondaBin ..." -ForegroundColor Cyan
        Copy-Item -Path (Join-Path $CondaBin "*.dll") -Destination $InternalDir -Force
    } else {
        Write-Host "[Sidecar] WARN: Conda Library\bin not found: $CondaBin" -ForegroundColor Yellow
    }

    # PyInstaller may pick mismatched stdlib extension modules from user site-packages.
    $StdlibPyds = @(
        "_ssl.pyd", "_ctypes.pyd", "_sqlite3.pyd", "_socket.pyd", "_hashlib.pyd",
        "_bz2.pyd", "_lzma.pyd", "_decimal.pyd", "_elementtree.pyd", "_uuid.pyd"
    )
    foreach ($pydName in $StdlibPyds) {
        $srcPyd = Join-Path $CondaDlls $pydName
        if (Test-Path $srcPyd) {
            Copy-Item -Path $srcPyd -Destination $InternalDir -Force
        }
    }

    Write-Host "[Sidecar] Conda runtime synced to: $InternalDir" -ForegroundColor Green
}

function Stop-SageDesktopProcesses {
    foreach ($procName in @("sage-desktop", "Sage")) {
        Get-Process -Name $procName -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Host "[Build] Stopping $($procName) process (PID $($_.Id))..." -ForegroundColor Yellow
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
}

function Remove-BuildDirectory {
    param([string]$Path)

    if (-not (Test-Path $Path)) { return }

    Stop-SageDesktopProcesses

    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            Write-Host "[Build] Cleanup attempt $attempt failed for: $Path" -ForegroundColor Yellow
            Write-Host "         $($_.Exception.Message)" -ForegroundColor Yellow
            Stop-SageDesktopProcesses
            Start-Sleep -Seconds 2
        }
    }

    Write-Host "[ERROR] Could not remove locked directory: $Path" -ForegroundColor Red
    Write-Host "Close Sage Desktop, file explorer windows under dist/, then retry the build." -ForegroundColor Yellow
    exit 1
}

$CondaExe = Find-CondaExe
if (-not $CondaExe) {
    Write-Host "[ERROR] Conda not found. Please install Miniconda or Anaconda." -ForegroundColor Red
    exit 1
}

Write-Host "Found Conda: $CondaExe" -ForegroundColor Green

$CondaBase = & $CondaExe info --base 2>$null
if (-not $CondaBase) {
    Write-Host "[ERROR] Failed to get Conda base directory" -ForegroundColor Red
    exit 1
}

$envExists = $false
try {
    $envList = & $CondaExe env list 2>$null
    if ($envList -match $EnvName) { $envExists = $true }
} catch {}

if ($envExists) {
    Write-Host "Conda environment '$EnvName' already exists." -ForegroundColor Green
} else {
    Write-Host "Creating Conda environment '$EnvName' (Python 3.11)..." -ForegroundColor Cyan
    & $CondaExe create -n $EnvName python=3.11 pip setuptools wheel -y
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create Conda environment" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Resolving Python executable for Conda environment '$EnvName'..." -ForegroundColor Cyan
$SagePython = Resolve-CondaEnvPython -CondaExe $CondaExe -EnvName $EnvName -CondaBase $CondaBase
if (-not $SagePython) {
    Write-Host "[ERROR] Python not found in Conda environment '$EnvName'. Check 'conda env list'." -ForegroundColor Red
    exit 1
}

$env:SAGE_PYTHON = $SagePython
$env:PYTHONNOUSERSITE = "1"
$env:PIP_USER = "0"
$EnvScriptsDir = Join-Path (Split-Path -Parent $SagePython) "Scripts"
if (Test-Path $EnvScriptsDir) {
    $env:PATH = "$EnvScriptsDir;$env:PATH"
}

Ensure-PythonPackagingTools -CondaExe $CondaExe -EnvName $EnvName -SagePythonParam $SagePython

Write-Host "Python: $(& $SagePython --version)" -ForegroundColor Cyan
Write-Host "Pip: $(& $SagePython -m pip --version)" -ForegroundColor Cyan

function Install-PythonDeps {
    param($RootDirParam, $CacheDirParam, $SagePythonParam)

    $ReqFile = Join-Path $RootDirParam "requirements.txt"
    $HashFile = Join-Path $CacheDirParam ".requirements.hash"
    $NewHash = Get-FileHash256 -FilePath $ReqFile
    if (Test-Path $HashFile) {
        $OldHash = Get-Content $HashFile
    } else {
        $OldHash = ""
    }

    $EnvOk = $false
    $pipList = & $SagePythonParam -m pip list 2>$null
    if ($pipList -match "requests") {
        $EnvOk = $true
    }

    if ($NewHash -eq $OldHash -and $EnvOk) {
        Write-Host "Python deps unchanged, skipping install." -ForegroundColor Green
    } else {
        Write-Host "Upgrading build tools..." -ForegroundColor Cyan
        $PipIndexUrl = if ($env:PIP_INDEX_URL) { $env:PIP_INDEX_URL } else { "https://mirrors.aliyun.com/pypi/simple" }
        Write-Host "Using pip index: $PipIndexUrl" -ForegroundColor Cyan

        & $SagePythonParam -m pip install --upgrade pip setuptools wheel --index-url $PipIndexUrl --no-user
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to upgrade Python build tools" -ForegroundColor Red
            exit 1
        }

        Write-Host "Installing deps..." -ForegroundColor Cyan
        & $SagePythonParam -m pip install -r $ReqFile --index-url $PipIndexUrl --no-user
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to install Python dependencies" -ForegroundColor Red
            exit 1
        }

        Write-Host "Replacing python-magic with python-magic-bin for Windows..." -ForegroundColor Cyan
        & $SagePythonParam -m pip uninstall -y python-magic 2>$null
        & $SagePythonParam -m pip install python-magic-bin --index-url $PipIndexUrl --no-user
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to install python-magic-bin" -ForegroundColor Red
            exit 1
        }

        Write-Host "Force reinstalling pure Python chardet..." -ForegroundColor Cyan
        & $SagePythonParam -m pip install --force-reinstall --no-binary=chardet,charset-normalizer chardet charset-normalizer --index-url $PipIndexUrl --no-user
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Falling back to official PyPI for chardet..." -ForegroundColor Yellow
            & $SagePythonParam -m pip install --force-reinstall --no-binary=chardet,charset-normalizer chardet charset-normalizer --index-url https://pypi.org/simple --no-user
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[ERROR] Failed to install chardet/charset-normalizer" -ForegroundColor Red
                exit 1
            }
        }

        & $SagePythonParam -c "import PyInstaller" 2>$null
        if ($LASTEXITCODE -ne 0) {
            & $SagePythonParam -m pip install pyinstaller --index-url $PipIndexUrl --no-user
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[ERROR] Failed to install PyInstaller" -ForegroundColor Red
                exit 1
            }
        }

        Write-Host "Ensuring python-magic-bin is installed for unstructured..." -ForegroundColor Cyan
        & $SagePythonParam -m pip install python-magic-bin --index-url $PipIndexUrl --no-user
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to verify python-magic-bin" -ForegroundColor Red
            exit 1
        }

        $NewHash | Out-File -FilePath $HashFile -Encoding UTF8
    }
}

Install-PythonDeps -RootDirParam $RootDir -CacheDirParam $CacheDir -SagePythonParam $SagePython

function Build-PythonSidecar {
    param($DistDirParam, $TauriSidecarDirParam, $AppDirParam, $RootDirParam, $ModeParam, $CacheDirParam, $SagePythonParam)

    Write-Host "[Sidecar] Building Python Sidecar (sage-desktop.spec)..." -ForegroundColor Cyan

    if ($ModeParam -eq "release") {
        Remove-BuildDirectory -Path $DistDirParam
    }
    if (-not (Test-Path $DistDirParam)) {
        New-Item -ItemType Directory -Force -Path $DistDirParam | Out-Null
    }

    $env:PYINSTALLER_CONFIG_DIR = Join-Path $RootDirParam ".pyinstaller"
    $env:PYTHONPATH = "$RootDirParam;$($env:PYTHONPATH)"
    $env:SAGE_PYI_MODE = if ($ModeParam -eq "release") { "release" } else { "debug" }

    Set-Location $AppDirParam

    $workPath = Join-Path $CacheDirParam "pyi-work"
    if (-not (Test-Path $workPath)) {
        New-Item -ItemType Directory -Force -Path $workPath | Out-Null
    }
    $specPath = Join-Path $AppDirParam "sage-desktop.spec"

    $pyiArgs = @(
        "--noconfirm",
        "--log-level=WARN",
        "--distpath", $DistDirParam,
        "--workpath", $workPath
    )
    if ($ModeParam -eq "release") {
        $pyiArgs += "--clean"
    }
    $pyiArgs += $specPath

    & $SagePythonParam -m PyInstaller @pyiArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] PyInstaller build failed" -ForegroundColor Red
        exit 1
    }

    Write-Host "[Sidecar] Cleaning dist files..." -ForegroundColor Cyan
    Get-ChildItem -Path $DistDirParam -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $DistDirParam -Recurse -File -Filter "*.pyc" | Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $DistDirParam -Recurse -File -Filter ".DS_Store" | Remove-Item -Force -ErrorAction SilentlyContinue

    Write-Host "[Sidecar] Resolving onedir root for data copies (_internal)..." -ForegroundColor Cyan
    $targetMcpDir = Join-Path $DistDirParam "sage-desktop"
    if (Test-Path (Join-Path $DistDirParam "sage-desktop\_internal")) {
        $targetMcpDir = Join-Path $DistDirParam "sage-desktop\_internal"
    }

    Sync-CondaRuntimeToSidecar -SagePythonParam $SagePythonParam -InternalDir $targetMcpDir

    $mcpServersSrc = Join-Path $RootDirParam "mcp_servers"
    if (Test-Path $mcpServersSrc) {
        Write-Host "[Sidecar] Copying mcp_servers to dist..." -ForegroundColor Cyan
        Copy-Item -Path $mcpServersSrc -Destination $targetMcpDir -Recurse -Force
        $mcpPath = Join-Path $targetMcpDir "mcp_servers"
        Get-ChildItem -Path $mcpPath -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $mcpPath -Recurse -Directory -Filter ".git" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $mcpPath -Recurse -File -Filter ".DS_Store" | Remove-Item -Force -ErrorAction SilentlyContinue
    }

    $skillsSrc = Join-Path $RootDirParam "app\skills"
    if (Test-Path $skillsSrc) {
        Write-Host "[Sidecar] Copying skills to dist..." -ForegroundColor Cyan
        Copy-Item -Path $skillsSrc -Destination $targetMcpDir -Recurse -Force
        $skillsPath = Join-Path $targetMcpDir "skills"
        Get-ChildItem -Path $skillsPath -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $skillsPath -Recurse -Directory -Filter ".git" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $skillsPath -Recurse -File -Filter ".DS_Store" | Remove-Item -Force -ErrorAction SilentlyContinue
    }

    $wikiSrc = Join-Path $RootDirParam "app\wiki"
    if (Test-Path $wikiSrc) {
        Write-Host "[Sidecar] Copying wiki to dist..." -ForegroundColor Cyan
        $wikiDst = Join-Path $targetMcpDir "wiki"
        if (Test-Path $wikiDst) { Remove-Item -Recurse -Force $wikiDst }
        Copy-Item -Path $wikiSrc -Destination $wikiDst -Recurse -Force
        Get-ChildItem -Path $wikiDst -Recurse -Directory -Filter "node_modules" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $wikiDst -Recurse -Directory -Filter ".vitepress" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $wikiDst -Recurse -File -Filter ".DS_Store" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    }

    $docsTargetRoot = Join-Path $targetMcpDir "docs"
    foreach ($lang in @("en", "zh")) {
        $langSrc = Join-Path $RootDirParam "docs\$lang"
        if (Test-Path $langSrc) {
            Write-Host "[Sidecar] Copying docs/$lang to dist..." -ForegroundColor Cyan
            $langDst = Join-Path $docsTargetRoot $lang
            New-Item -ItemType Directory -Force -Path $langDst | Out-Null
            Get-ChildItem -Path $langSrc -Filter "*.md" -File | ForEach-Object {
                Copy-Item -Path $_.FullName -Destination $langDst -Force
            }
        }
    }

    Set-Location $RootDirParam

    Write-Host "[Sidecar] Copying to Tauri Sidecar dir..." -ForegroundColor Cyan
    Remove-BuildDirectory -Path $TauriSidecarDirParam
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

    $env:NODE_OPTIONS = "--max-old-space-size=4096"
    npm run build
    Set-Location $RootDirParam
}

function Prepare-BundledNodeRuntime {
    param($TauriNodeSidecarDirParam)

    Write-Host "[Node Runtime] Preparing bundled Node runtime..." -ForegroundColor Cyan

    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] node not found. Cannot prepare sidecar/node." -ForegroundColor Red
        exit 1
    }

    if (Test-Path $TauriNodeSidecarDirParam) {
        Remove-Item -Recurse -Force $TauriNodeSidecarDirParam
    }
    New-Item -ItemType Directory -Force -Path $TauriNodeSidecarDirParam | Out-Null

    if ($env:SAGE_BUNDLED_NODE_SOURCE) {
        $NodeRoot = $env:SAGE_BUNDLED_NODE_SOURCE
        if (-not (Test-Path $NodeRoot)) {
            Write-Host "[ERROR] Custom Node runtime directory not found: $NodeRoot" -ForegroundColor Red
            exit 1
        }

        Get-ChildItem -Force $NodeRoot |
            ForEach-Object {
                Copy-Item -Path $_.FullName -Destination $TauriNodeSidecarDirParam -Recurse -Force
            }

        Write-Host "[Node Runtime] Using custom source: $NodeRoot" -ForegroundColor Green
        Write-Host "[Node Runtime] Synced to: $TauriNodeSidecarDirParam" -ForegroundColor Green
        return
    }

    $NodeExe = (Resolve-Path ((Get-Command node -ErrorAction Stop).Source)).Path
    $NodeDir = Split-Path -Parent $NodeExe
    $NpmPackageDir = Join-Path $NodeDir "node_modules/npm"

    if (-not (Test-Path $NpmPackageDir)) {
        $NpmCmd = (Get-Command npm -ErrorAction Stop).Source
        $NpmDir = Split-Path -Parent $NpmCmd
        $Candidate = Join-Path $NpmDir "node_modules/npm"
        if (Test-Path $Candidate) {
            $NpmPackageDir = $Candidate
        }
    }

    if (-not (Test-Path $NodeExe)) {
        Write-Host "[ERROR] Node executable not found: $NodeExe" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $NpmPackageDir)) {
        Write-Host "[ERROR] npm package directory not found: $NpmPackageDir" -ForegroundColor Red
        exit 1
    }

    $TargetNodeModulesDir = Join-Path $TauriNodeSidecarDirParam "node_modules"
    New-Item -ItemType Directory -Force -Path $TargetNodeModulesDir | Out-Null

    Copy-Item -Path $NodeExe -Destination (Join-Path $TauriNodeSidecarDirParam "node.exe") -Force
    Copy-Item -Path $NpmPackageDir -Destination (Join-Path $TargetNodeModulesDir "npm") -Recurse -Force

    Write-Host "[Node Runtime] Node executable: $NodeExe" -ForegroundColor Green
    Write-Host "[Node Runtime] npm package dir: $NpmPackageDir" -ForegroundColor Green
    Write-Host "[Node Runtime] Synced minimal runtime to: $TauriNodeSidecarDirParam" -ForegroundColor Green
}

Write-Host ">>> Starting build tasks..." -ForegroundColor Cyan

Build-PythonSidecar -DistDirParam $DistDir -TauriSidecarDirParam $TauriSidecarDir -AppDirParam $AppDir -RootDirParam $RootDir -ModeParam $Mode -CacheDirParam $CacheDir -SagePythonParam $SagePython
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

Prepare-BundledNodeRuntime -TauriNodeSidecarDirParam $TauriNodeSidecarDir

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
# Skip updater artifact signing when no private key is available (pubkey in tauri.conf.json is for runtime verify only)
$env:TAURI_SKIP_SIGNATURE = "true"

Write-Host "Building Tauri application (this may take a while)..." -ForegroundColor Cyan

$Process = Start-Process -FilePath $TauriCmd -ArgumentList $TauriArgs -NoNewWindow -Wait -PassThru -WorkingDirectory $TauriDir
if ($Process.ExitCode -ne 0) {
  Write-Host "[ERROR] Tauri build failed" -ForegroundColor Red
  exit $Process.ExitCode
}
 
Write-Host "======================================"
Write-Host " Build completed successfully!"
Write-Host "======================================"
