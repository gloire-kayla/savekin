$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Find-SaveKinPython {
    $searchPaths = @(
        'C:/Users/PC/AppData/Local/Python/pythoncore-3.14-64/python.exe',
        "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python314\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($p in $searchPaths) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            try {
                $test = & $p -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $test) { return $p }
            } catch {}
        }
    }
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        try {
            $test = & py -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $test) { return "py" }
        } catch {}
    }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        try {
            $test = & python -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $test) { return "python" }
        } catch {}
    }
    $wildcards = @(
        "$env:LOCALAPPDATA\Programs\Python\*\python.exe",
        "$env:LOCALAPPDATA\Python\*\python.exe",
        "$env:ProgramFiles\Python*\python.exe"
    )
    foreach ($w in $wildcards) {
        $matches = Get-Item $w -ErrorAction SilentlyContinue
        foreach ($m in $matches) {
            try {
                $test = & $m.FullName -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $test) { return $m.FullName }
            } catch {}
        }
    }
    return "python"
}

$py = Find-SaveKinPython
if ($py -eq 'py') {
    & py -3 server.py
} else {
    & $py server.py
}

