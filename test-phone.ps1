param([switch]$WebOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$saveKinAdb = 'C:/Users/PC/AppData/Local/Android/Sdk/platform-tools/adb.exe'
if (-not (Test-Path -LiteralPath $saveKinAdb)) { throw 'Android platform-tools are required.' }
& $saveKinAdb devices
& $saveKinAdb reverse tcp:8000 tcp:8000
if ($LASTEXITCODE -ne 0) { throw 'Unlock your phone and approve USB debugging, then retry.' }
if ($WebOnly) { Write-Host 'Open http://127.0.0.1:8000 in your phone browser. Keep start.ps1 running.'; exit }
& $saveKinAdb reverse tcp:8081 tcp:8081
$saveKinRuntime = 'C:/Users/PC/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin'
$saveKinNode = Join-Path $saveKinRuntime 'node.exe'
if (-not (Test-Path -LiteralPath $saveKinNode)) { $saveKinNode = 'node' }
$env:PATH = "$saveKinRuntime;C:/Users/PC/AppData/Local/Android/Sdk/platform-tools;" + $env:PATH
$env:EXPO_PUBLIC_API_URL = 'http://127.0.0.1:8000'
$env:EXPO_OFFLINE = '1'
Set-Location -LiteralPath (Join-Path $PSScriptRoot 'mobile')
& $saveKinNode node_modules/expo/bin/cli start --localhost --android --port 8081
