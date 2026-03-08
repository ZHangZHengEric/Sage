$ErrorActionPreference = "Stop"

# ===============================
# Path Configuration
# ===============================
$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "../../..")).Path
$AppDir = Join-Path $RootDir "app/desktop"
$UiDir = Join-Path $AppDir "ui"
$TauriDir = Join-Path $AppDir "tauri"
$TauriSidecarDir = Join-Path $TauriDir "sidecar"
$TauriBinDir = Join-Path $TauriDir "bin"
$EnvName = "sage-desktop-env"
$Mode = "debug"

Write-Host "======================================"
Write-Host "Sage Desktop Dev Environment ($Mode)"
Write-Host "Root: $RootDir"
Write-Host "======================================"

# ===============================
# Function: Find Conda Executable
# ===============================
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

# ===============================
# Initialize Conda
# ===============================
$CondaBase = & $CondaExe info --base 2>$null
if (-not $CondaBase) {
    Write-Host "[ERROR] Failed to get Conda base directory" -ForegroundColor Red
    exit 1
}

& $CondaExe shell.powershell hook | Out-String | Invoke-Expression

# ===============================
# Check or Create Conda Environment
# ===============================
$envExists = $false
try {
    $envList = & $CondaExe env list 2>$null
    if ($envList -match $EnvName) { $envExists = $true }
} catch {}

if ($envExists) {
    Write-Host "Conda environment '$EnvName' already exists." -ForegroundColor Green
} else {
    Write-Host "Creating Conda environment '$EnvName' (Python 3.11)..." -ForegroundColor Cyan
    & $CondaExe create -n $EnvName python=3.11 -y
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create Conda environment" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Activating Conda environment '$EnvName'..." -ForegroundColor Cyan
conda activate $EnvName
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to activate Conda environment" -ForegroundColor Red
    exit 1
}

# ===============================
# Set Python Path and Install Dependencies
# ===============================
$SagePython = (Get-Command python).Source
$env:SAGE_PYTHON = $SagePython
Write-Host "Set SAGE_PYTHON: $SagePython" -ForegroundColor Green

Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
pip install -r "$AppDir\core\requirements.txt" --index-url https://pypi.org/simple

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Installing PyInstaller..." -ForegroundColor Cyan
    pip install pyinstaller --index-url https://pypi.org/simple
}

# ===============================
# Setup Python Sidecar
# ===============================
Write-Host "Setting up Python Sidecar..." -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $TauriBinDir | Out-Null
New-Item -ItemType Directory -Force -Path $TauriSidecarDir | Out-Null

# Link resources for dev mode
Write-Host "Linking dev mode resources..." -ForegroundColor Cyan
Remove-Item -Path "$TauriSidecarDir\skills" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$TauriSidecarDir\mcp_servers" -Recurse -Force -ErrorAction SilentlyContinue

$skillsSource = "$RootDir\app\skills"
$mcpSource = "$RootDir\mcp_servers"

$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

try {
    if ($IsAdmin) {
        New-Item -ItemType SymbolicLink -Path "$TauriSidecarDir\skills" -Target $skillsSource -ErrorAction Stop | Out-Null
        New-Item -ItemType SymbolicLink -Path "$TauriSidecarDir\mcp_servers" -Target $mcpSource -ErrorAction Stop | Out-Null
        Write-Host "Symbolic links created successfully." -ForegroundColor Green
    } else {
        Copy-Item -Path $skillsSource -Destination "$TauriSidecarDir\skills" -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item -Path $mcpSource -Destination "$TauriSidecarDir\mcp_servers" -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Not admin: resources copied instead of symlinks." -ForegroundColor Yellow
    }
} catch {
    Write-Host "Failed to create symlinks; copied resources instead." -ForegroundColor Yellow
}

# Create Sidecar wrapper
$PythonExec = python -c "import sys; print(sys.executable)"
$SidecarWrapper = "$TauriSidecarDir\sage-desktop.cmd"

$WrapperContent = @"
@echo off
set PYTHONPATH=$RootDir;%PYTHONPATH%
set AGENT_BROWSER_HEADED=1
"$PythonExec" "$AppDir\entry.py" %*
"@

$WrapperContent | Out-File -FilePath $SidecarWrapper -Encoding ASCII
New-Item -ItemType File -Path "$TauriSidecarDir\.keep" -Force | Out-Null
Write-Host "Sidecar wrapper created: $SidecarWrapper" -ForegroundColor Green

# ===============================
# Frontend Setup
# ===============================
Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
Set-Location $UiDir

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] npm not found. Please install Node.js." -ForegroundColor Red
    exit 1
}

npm install
Set-Location $RootDir

# ===============================
# Build Tauri
# ===============================
Set-Location $TauriDir

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Cargo not found. Please install Rust." -ForegroundColor Red
    exit 1
}

$linkExe = Get-Command link.exe -ErrorAction SilentlyContinue
if (-not $linkExe) {
    Write-Host "[WARN] Visual Studio Build Tools (link.exe) not found." -ForegroundColor Yellow
    Write-Host "Please install 'Desktop development with C++' workload." -ForegroundColor Cyan
}

try {
    $TauriVersionRaw = & cargo tauri --version 2>$null
    if ($TauriVersionRaw) {
        $TauriCliVersion = $TauriVersionRaw -replace ".*?(\d+\.\d+).*", '$1'
    } else {
        $TauriCliVersion = $null
    }
} catch {
    $TauriCliVersion = $null
}

if (-not $TauriCliVersion) {
    Write-Host "Installing tauri-cli v2..." -ForegroundColor Cyan
    cargo install tauri-cli --version "^2" --locked
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install tauri-cli with --locked, trying without..." -ForegroundColor Yellow
        cargo install tauri-cli --version "^2"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to install tauri-cli." -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host "======================================"
Write-Host "Dev server starting..."
Write-Host "======================================"

cargo tauri dev