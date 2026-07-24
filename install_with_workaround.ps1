# Alternative installation script that tries to work around path length issues
# This script installs packages in a specific order to avoid path issues

$ErrorActionPreference = "Continue"

Write-Host "Installing packages with workaround for long path issues..." -ForegroundColor Yellow
Write-Host ""

$venvPython = ".\venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Error: Virtual environment not found!" -ForegroundColor Red
    exit 1
}

# Step 1: Install basic dependencies first
Write-Host "Step 1: Installing basic dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install fastapi uvicorn jinja2 python-multipart paho-mqtt websockets psutil requests schedule

# Step 2: Install numpy and opencv (these should work)
Write-Host "Step 2: Installing numpy and opencv..." -ForegroundColor Cyan
& $venvPython -m pip install "numpy>=1.26.0,<2.0.0" "opencv-python==4.8.1.78" "Pillow>=10.0.0"

# Step 3: Try installing PyTorch with different methods
Write-Host "Step 3: Attempting to install PyTorch..." -ForegroundColor Cyan
Write-Host "  Trying method 1: Direct install..." -ForegroundColor Yellow

$torchInstalled = $false

# Method 1: Try direct install
try {
    & $venvPython -m pip install torch torchvision 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $torchInstalled = $true
        Write-Host "  ✓ PyTorch installed successfully!" -ForegroundColor Green
    }
} catch {
    Write-Host "  ✗ Method 1 failed" -ForegroundColor Red
}

# Method 2: Try CPU-only version
if (-not $torchInstalled) {
    Write-Host "  Trying method 2: CPU-only version..." -ForegroundColor Yellow
    try {
        & $venvPython -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $torchInstalled = $true
            Write-Host "  ✓ PyTorch (CPU) installed successfully!" -ForegroundColor Green
        }
    } catch {
        Write-Host "  ✗ Method 2 failed" -ForegroundColor Red
    }
}

# Method 3: Try installing to user site
if (-not $torchInstalled) {
    Write-Host "  Trying method 3: User site installation..." -ForegroundColor Yellow
    try {
        & $venvPython -m pip install --user torch torchvision 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $torchInstalled = $true
            Write-Host "  ✓ PyTorch installed to user site!" -ForegroundColor Green
        }
    } catch {
        Write-Host "  ✗ Method 3 failed" -ForegroundColor Red
    }
}

if (-not $torchInstalled) {
    Write-Host ""
    Write-Host "⚠️  PyTorch installation failed due to path length limitations." -ForegroundColor Red
    Write-Host "Please enable long path support (run enable_long_paths.ps1 as Admin) or use a shorter path." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# Step 4: Install ultralytics and remaining packages
Write-Host "Step 4: Installing ultralytics and remaining packages..." -ForegroundColor Cyan
& $venvPython -m pip install ultralytics==8.0.196
& $venvPython -m pip install itsdangerous python-jose[cryptography] passlib[bcrypt] pyarmor

Write-Host ""
Write-Host "✓ Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To verify installation, run:" -ForegroundColor Cyan
Write-Host "  .\venv\Scripts\python.exe -c 'import torch; import ultralytics; print(\"OK\")'" -ForegroundColor White

