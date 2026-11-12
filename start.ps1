$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$gatherSavePython = 'C:/Users/PC/AppData/Local/Python/pythoncore-3.14-64/python.exe'
if (Test-Path -LiteralPath $gatherSavePython) {
    & $gatherSavePython server.py
} else {
    python server.py
}
