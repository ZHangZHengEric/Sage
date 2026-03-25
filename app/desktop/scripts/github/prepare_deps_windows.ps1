$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../../../..")).Path
$AppDir = Join-Path $RootDir "app/desktop"
$UiDir = Join-Path $AppDir "ui"
$CacheDir = Join-Path $AppDir ".build_cache"

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

Write-Host "Preparing desktop dependencies for windows/x86_64..." -ForegroundColor Cyan

$requirementsHash = Get-FileHash256 -FilePath (Join-Path $RootDir "requirements.txt")
$requirementsHash | Out-File -FilePath (Join-Path $CacheDir ".requirements.hash") -Encoding UTF8

Set-Location $UiDir
npm install --prefer-offline --no-audit --no-fund
$packageLockHash = Get-FileHash256 -FilePath (Join-Path $UiDir "package-lock.json")
$packageLockHash | Out-File -FilePath (Join-Path $CacheDir ".package-lock.hash") -Encoding UTF8

Write-Host "Preparing bundled Node runtime cache..." -ForegroundColor Cyan
$cacheNodeDir = Join-Path $CacheDir "node-runtime\windows-x86_64"
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

Set-Location $RootDir

Write-Host "Dependency preparation completed." -ForegroundColor Green
