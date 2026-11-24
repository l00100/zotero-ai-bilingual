$ErrorActionPreference = 'Stop'
$pythonCommand = Join-Path $env:LOCALAPPDATA 'HJFY-AI-Reader\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonCommand)) { throw 'Run the Windows service installer first.' }
& $pythonCommand (Join-Path $PSScriptRoot 'windows_setup.py') --start-only
if ($LASTEXITCODE -ne 0) { throw 'Service startup failed. See the error above.' }
