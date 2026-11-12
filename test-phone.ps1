param([switch]$WebOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$adbCandidates = @(
    "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
    "$env:ANDROID_HOME\platform-tools\adb.exe",
    'C:/Users/PC/AppData/Local/Android/Sdk/platform-tools/adb.exe'
)
$saveKinAdb = $null
foreach ($cand in $adbCandidates) {
    if ($cand -and (Test-Path -LiteralPath $cand)) { $saveKinAdb = $cand; break }
}
if (-not $saveKinAdb) {
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { $saveKinAdb = $cmd.Source }
}
if (-not $saveKinAdb) { throw 'Android platform-tools (adb.exe) could not be located. Install Android SDK or add adb to PATH.' }

& $saveKinAdb devices
& $saveKinAdb reverse tcp:8000 tcp:8000
if ($LASTEXITCODE -ne 0) { throw 'Unlock your phone and approve USB debugging, then retry.' }
if ($WebOnly) { Write-Host 'Open http://127.0.0.1:8000 in your phone browser. Keep start.ps1 running.'; exit }
& $saveKinAdb reverse tcp:8081 tcp:8081

$saveKinNode = $null
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) { $saveKinNode = $nodeCmd.Source }
if (-not $saveKinNode) {
    $nodeCandidates = @(
        "$env:ProgramFiles\nodejs\node.exe",
        "$env:LOCALAPPDATA\Programs\nodejs\node.exe",
        'C:/Users/PC/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin/node.exe'
    )
    foreach ($cand in $nodeCandidates) {
        if ($cand -and (Test-Path -LiteralPath $cand)) { $saveKinNode = $cand; break }
    }
}
if (-not $saveKinNode) { $saveKinNode = 'node' }

$env:EXPO_PUBLIC_API_URL = 'http://127.0.0.1:8000'
$env:EXPO_OFFLINE = '1'
Set-Location -LiteralPath (Join-Path $PSScriptRoot 'mobile')
& $saveKinNode node_modules/expo/bin/cli start --localhost --android --port 8081
