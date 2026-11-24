$ErrorActionPreference = 'Stop'
$pythonCommand = $null
foreach ($candidate in @('python3.12.exe', 'python3.exe', 'python.exe')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    & $found.Source -c 'import sys;sys.exit(0 if (3,10)<=sys.version_info[:2]<(3,14) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { $pythonCommand = $found.Source; break }
}
if (-not $pythonCommand) { throw 'Python 3.10-3.13 is required. Please install Python 3.12 and run this script again.' }
& $pythonCommand (Join-Path $PSScriptRoot 'windows_setup.py') @args
if ($LASTEXITCODE -ne 0) { throw 'Service installation did not finish. See the error above.' }
