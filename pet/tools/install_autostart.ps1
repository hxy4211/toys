# Install autostart for the Xiaomian desktop pet.
# Called by install_autostart.bat (double-click it once).
# ASCII only, so Windows PowerShell 5.1 parses it without encoding issues.
$ErrorActionPreference = 'Stop'

$pet = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$vbs = Join-Path $pet 'start_pet.vbs'
if (-not (Test-Path $vbs)) {
    Write-Host "ERROR: not found: $vbs" -ForegroundColor Red
    exit 1
}

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

Write-Host ("[OK] autostart installed: {0}" -f $lnk) -ForegroundColor Green

# Start the watchdog right now as well.
& (Join-Path $env:WINDIR 'System32\wscript.exe') $vbs
Write-Host "[OK] watchdog started. Open DSH -> pet appears; close DSH -> pet exits." -ForegroundColor Green
