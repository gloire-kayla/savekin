param([switch]$RestartLocal, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$saveKinConnection = New-Object System.Net.Sockets.TcpClient
try {
    $saveKinConnection.Connect('127.0.0.1', 8000)
    if (-not $RestartLocal -and -not $CheckOnly) {
        throw 'SaveKin is already running. Use .\start-sandbox.ps1 -RestartLocal, or -CheckOnly to validate credentials without restarting.'
    }
} catch [System.Net.Sockets.SocketException] {
    # The port is available; continue to interactive setup.
} finally {
    $saveKinConnection.Dispose()
}

Write-Host 'SaveKin PayPal sandbox setup. Use sandbox credentials only. Nothing is saved to disk.'
$saveKinClientId = Read-Host 'Sandbox app client ID'
$saveKinRecipient = Read-Host 'Sandbox treasurer account email (must match the group receiving account)'
$saveKinWebhookId = Read-Host 'Webhook ID (optional until an HTTPS listener is configured)'
if ([string]::IsNullOrWhiteSpace($saveKinClientId) -or $saveKinRecipient -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') {
    throw 'A sandbox client ID and valid treasurer email are required.'
}
$saveKinSecret = Read-Host 'Sandbox app secret (hidden)' -AsSecureString
$saveKinPointer = [IntPtr]::Zero
$saveKinPrevious = @{}
$saveKinKeys = @('PAYMENT_MODE', 'PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET', 'PAYPAL_TREASURER_EMAIL', 'PAYPAL_WEBHOOK_ID')
foreach ($saveKinKey in $saveKinKeys) {
    $saveKinPrevious[$saveKinKey] = [Environment]::GetEnvironmentVariable($saveKinKey, 'Process')
}
try {
    $saveKinPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($saveKinSecret)
    $env:PAYMENT_MODE = 'sandbox'
    $env:PAYPAL_CLIENT_ID = $saveKinClientId.Trim()
    $env:PAYPAL_TREASURER_EMAIL = $saveKinRecipient.Trim().ToLowerInvariant()
    $env:PAYPAL_WEBHOOK_ID = $saveKinWebhookId.Trim()
    $env:PAYPAL_CLIENT_SECRET = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($saveKinPointer)
    $saveKinPython = 'C:/Users/PC/AppData/Local/Python/pythoncore-3.14-64/python.exe'
    if (-not (Test-Path -LiteralPath $saveKinPython)) { $saveKinPython = 'python' }
    & $saveKinPython (Join-Path $PSScriptRoot 'sandbox_check.py')
    if ($LASTEXITCODE -ne 0) { throw 'Sandbox check failed. The existing server was left running.' }
    if ($CheckOnly) { return }
    if ($RestartLocal) {
        $saveKinListeners = @(netstat -ano -p tcp | Select-String '^\s*TCP\s+127\.0\.0\.1:8000\s+\S+\s+LISTENING\s+(\d+)\s*$')
        if ($saveKinListeners.Count -gt 1) { throw 'Multiple listeners found. Stop the backend manually before continuing.' }
        if ($saveKinListeners.Count -eq 1) {
            $saveKinProcessId = [int]$saveKinListeners[0].Matches[0].Groups[1].Value
            $saveKinProcess = Get-Process -Id $saveKinProcessId -ErrorAction Stop
            $saveKinServedCode = (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/app.js' -UseBasicParsing -TimeoutSec 5).Content
            $saveKinLocalCode = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'web/app.js') -Raw -Encoding UTF8
            if ($saveKinServedCode -ne $saveKinLocalCode -or $saveKinProcess.ProcessName -notmatch '^python(\d+(\.\d+)*)?$') {
                throw 'Port 8000 could not be verified as this SaveKin server. No process was stopped.'
            }
            Stop-Process -Id $saveKinProcessId -ErrorAction Stop
            Write-Host 'Restarting the verified SaveKin development server in sandbox mode.'
        }
    }
    & (Join-Path $PSScriptRoot 'start.ps1')
} finally {
    foreach ($saveKinKey in $saveKinKeys) {
        [Environment]::SetEnvironmentVariable($saveKinKey, $saveKinPrevious[$saveKinKey], 'Process')
    }
    if ($saveKinPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($saveKinPointer) }
    $saveKinSecret.Dispose()
}
