$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../../../..")).Path
$AppDir = Join-Path $RootDir "app/desktop"
$UiDir = Join-Path $AppDir "ui"
$CacheDir = Join-Path $AppDir ".build_cache"
$BuildReqFile = Join-Path $AppDir "scripts/github/requirements-build.txt"

if (-not (Test-Path $CacheDir)) {
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
}

function Get-FileHash256 {
    param([string]$FilePath)
    if (Test-Path $FilePath) {
        return (Get-FileHash -Path $FilePath -Algorithm SHA256).Hash
    }
    return "unknown"
}

function Resolve-PythonExe {
    if ($env:PYTHON_BIN -and (Test-Path $env:PYTHON_BIN)) {
        return $env:PYTHON_BIN
    }

    if ($env:pythonLocation) {
        $candidate = Join-Path $env:pythonLocation "python.exe"
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return (Resolve-Path $cmd.Source).Path
    }

    return $null
}

$PythonExe = Resolve-PythonExe
if (-not $PythonExe) {
    Write-Host "[ERROR] Python executable not found." -ForegroundColor Red
    exit 1
}

Write-Host "Preparing desktop dependencies for windows/x86_64..." -ForegroundColor Cyan
Write-Host "Python executable: $PythonExe" -ForegroundColor Cyan

$requirementsHash = Get-FileHash256 -FilePath (Join-Path $RootDir "requirements.txt")
$requirementsHash | Out-File -FilePath (Join-Path $CacheDir ".requirements.hash") -Encoding UTF8

$PipIndexUrl = if ($env:PIP_INDEX_URL) { $env:PIP_INDEX_URL } else { "https://pypi.org/simple" }
$WheelhouseDir = Join-Path $CacheDir "wheelhouse"
if ((Test-Path $WheelhouseDir) -and $null -ne (Get-ChildItem -Path $WheelhouseDir -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    Write-Host "Reusing cached Python wheelhouse at $WheelhouseDir..." -ForegroundColor Green
} else {
    if (Test-Path $WheelhouseDir) {
        Remove-Item -Path $WheelhouseDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $WheelhouseDir | Out-Null

    Write-Host "Preparing Python wheelhouse at $WheelhouseDir..." -ForegroundColor Cyan
    & $PythonExe -m pip install --upgrade -r $BuildReqFile --index-url $PipIndexUrl
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to upgrade packaging toolchain for wheelhouse preparation." -ForegroundColor Red
        exit 1
    }

    & $PythonExe -m pip download --dest $WheelhouseDir -r $BuildReqFile --index-url $PipIndexUrl
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to download build toolchain into wheelhouse." -ForegroundColor Red
        exit 1
    }

    & $PythonExe -m pip download --dest $WheelhouseDir -r (Join-Path $RootDir "requirements.txt") --index-url $PipIndexUrl
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to download requirements into wheelhouse." -ForegroundColor Red
        exit 1
    }

    Get-ChildItem -Path $WheelhouseDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'chardet-*' -or $_.Name -like 'charset_normalizer-*' -or $_.Name -like 'charset-normalizer-*' } |
        Remove-Item -Force -ErrorAction SilentlyContinue

    & $PythonExe -m pip wheel --wheel-dir $WheelhouseDir --no-build-isolation --no-binary=chardet,charset-normalizer chardet charset-normalizer
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to build pure Python chardet/charset-normalizer wheels." -ForegroundColor Red
        exit 1
    }
}

Set-Location $UiDir
npm install --prefer-offline --no-audit --no-fund
$packageLockHash = Get-FileHash256 -FilePath (Join-Path $UiDir "package-lock.json")
$packageLockHash | Out-File -FilePath (Join-Path $CacheDir ".package-lock.hash") -Encoding UTF8

Write-Host "Preparing bundled Node runtime cache..." -ForegroundColor Cyan
$cacheNodeDir = Join-Path $CacheDir "node-runtime\windows-x86_64"
if ((Test-Path (Join-Path $cacheNodeDir "node.exe")) -and (Test-Path (Join-Path $cacheNodeDir "node_modules\npm"))) {
    Write-Host "Reusing cached bundled Node runtime at $cacheNodeDir..." -ForegroundColor Green
} else {
    if (Test-Path $cacheNodeDir) {
        Remove-Item -Path $cacheNodeDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $cacheNodeDir | Out-Null

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

    if (-not (Test-Path $NpmPackageDir)) {
        Write-Host "[ERROR] npm package directory not found: $NpmPackageDir" -ForegroundColor Red
        exit 1
    }

    $TargetNodeModulesDir = Join-Path $cacheNodeDir "node_modules"
    New-Item -ItemType Directory -Force -Path $TargetNodeModulesDir | Out-Null

    Copy-Item -Path $NodeExe -Destination (Join-Path $cacheNodeDir "node.exe") -Force
    Copy-Item -Path $NpmPackageDir -Destination (Join-Path $TargetNodeModulesDir "npm") -Recurse -Force
}

Set-Location $RootDir

Write-Host "Dependency preparation completed." -ForegroundColor Green
