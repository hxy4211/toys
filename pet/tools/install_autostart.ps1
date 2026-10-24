# Install autostart for the Xiaomian desktop pet.
# Called by install_autostart.bat (double-click it once).
# ASCII only, so Windows PowerShell 5.1 parses it without encoding issues.
#
# Two mechanisms are written so autostart survives even if one gets lost:
#   1) HKCU Run key            (primary, reliable)
#   2) Startup folder shortcut (fallback, best effort)
$ErrorActionPreference = 'Stop'

$pet = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$vbs = Join-Path $pet 'start_pet.vbs'
if (-not (Test-Path $vbs)) {
    Write-Host "ERROR: not found: $vbs" -ForegroundColor Red
    exit 1
}

$cmd = 'wscript.exe "' + $vbs + '"'

# 1) HKCU Run key
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Set-ItemProperty -Path $runKey -Name 'XiaomianPet' -Value $cmd
Write-Host "[OK] Run key installed: XiaomianPet = $cmd" -ForegroundColor Green

# 2) Startup folder shortcut (best effort)
try {
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup 'XiaomianPet.lnk'
    $sh = New-Object -ComObject WScript.Shell
    $sc = $sh.CreateShortcut($lnk)
    $sc.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $sc.Arguments = '"' + $vbs + '"'
    $sc.WorkingDirectory = $pet
    $sc.WindowStyle = 7
    $sc.Description = 'Xiaomian desktop pet watchdog (appears when DSH is open)'
    $sc.Save()
    Write-Host "[OK] startup shortcut: $lnk" -ForegroundColor Green
}
catch {
    Write-Host "[WARN] startup shortcut skipped (Run key alone is enough): $($_.Exception.Message)" -ForegroundColor Yellow
}

# Start the watchdog right now.
& (Join-Path $env:WINDIR 'System32\wscript.exe') $vbs
Write-Host "[OK] watchdog started. Open DSH -> pet appears; close DSH -> pet exits." -ForegroundColor Green
