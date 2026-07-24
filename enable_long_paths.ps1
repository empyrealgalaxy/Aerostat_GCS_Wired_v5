# Script to Enable Long Path Support on Windows
# Run this as Administrator

Write-Host "Checking current long path status..." -ForegroundColor Yellow

$currentValue = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -ErrorAction SilentlyContinue

if ($currentValue -and $currentValue.LongPathsEnabled -eq 1) {
    Write-Host "Long paths are already enabled!" -ForegroundColor Green
    exit 0
}

Write-Host "Long paths are currently disabled." -ForegroundColor Red
Write-Host ""
Write-Host "To enable long path support:" -ForegroundColor Yellow
Write-Host "1. Run PowerShell as Administrator" -ForegroundColor Cyan
Write-Host "2. Run this command:" -ForegroundColor Cyan
Write-Host ""
Write-Host '   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force' -ForegroundColor White
Write-Host ""
Write-Host "3. Restart your computer" -ForegroundColor Cyan
Write-Host "4. Then run: .\venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor Cyan
Write-Host ""

# Check if running as admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    Write-Host "Running as Administrator - Enabling long paths now..." -ForegroundColor Green
    try {
        New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force | Out-Null
        Write-Host "✓ Long paths enabled successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "⚠️  IMPORTANT: You must restart your computer for this to take effect!" -ForegroundColor Yellow
        Write-Host ""
        $restart = Read-Host "Do you want to restart now? (Y/N)"
        if ($restart -eq 'Y' -or $restart -eq 'y') {
            Restart-Computer -Force
        } else {
            Write-Host "Please restart manually, then run the pip install command." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Error enabling long paths: $_" -ForegroundColor Red
    }
} else {
    Write-Host "⚠️  Not running as Administrator!" -ForegroundColor Red
    Write-Host "Please run this script as Administrator to enable long paths." -ForegroundColor Yellow
}

