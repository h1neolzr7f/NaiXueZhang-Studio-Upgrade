param()

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

function Write-Check {
    param([string]$Name, [string]$Status, [string]$Detail)
    Write-Host ("[{0}] {1}: {2}" -f $Status, $Name, $Detail)
}

Write-Host "NaiXueZhang Studio doctor (read-only)"
Write-Host "root=$root"
Write-Host ""

$pythonCandidates = @(
    (Join-Path $root "runtime\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
)
$resolvedPython = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $resolvedPython) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $resolvedPython = $cmd.Source }
}
if ($resolvedPython) {
    Write-Check "python" "OK" $resolvedPython
    try {
        $ver = & $resolvedPython -c "import sys; print(sys.version.split()[0])"
        Write-Check "python.version" "OK" $ver
    } catch {
        Write-Check "python.version" "WARN" $_.Exception.Message
    }
} else {
    Write-Check "python" "FAIL" "no runtime, .venv, or python.exe on PATH"
}

$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $nodeVer = & node -v
    Write-Check "node" "OK" $nodeVer
} else {
    Write-Check "node" "FAIL" "Node.js 20+ required for verify.ps1"
}

foreach ($name in @("requirements.core.lock.txt", "requirements.lock.txt", "INSTALL.bat", "START_GALLERY.bat", "一键启动.bat")) {
    $path = Join-Path $root $name
    if (Test-Path -LiteralPath $path) {
        Write-Check "file.$name" "OK" "present"
    } else {
        Write-Check "file.$name" "FAIL" "missing"
    }
}

if ($resolvedPython) {
    try {
        & $resolvedPython -m pip check | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Check "pip.check" "OK" "no broken requirements"
        } else {
            Write-Check "pip.check" "WARN" "pip check reported issues"
        }
    } catch {
        Write-Check "pip.check" "WARN" $_.Exception.Message
    }
}

$port = 8797
try {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        $pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
        Write-Check "port.8797" "WARN" ("in use by PID {0}" -f ($pids -join ","))
    } else {
        Write-Check "port.8797" "OK" "free"
    }
} catch {
    Write-Check "port.8797" "WARN" "could not query listeners"
}

$dpapi = Test-Path "HKLM:\SOFTWARE\Microsoft\Cryptography"
if ($dpapi) {
    Write-Check "dpapi" "OK" "Windows cryptography key present"
} else {
    Write-Check "dpapi" "FAIL" "DPAPI unavailable; secrets must fail closed"
}

if (Test-Path (Join-Path $root ".git")) {
    $status = git -C $root status --porcelain
    if ($status) {
        Write-Check "git.worktree" "WARN" "dirty worktree (not listing paths)"
    } else {
        Write-Check "git.worktree" "OK" "clean"
    }
}

$setupWeb = Join-Path $root "setup_web.ps1"
if (Test-Path -LiteralPath $setupWeb) {
    $setupText = Get-Content -LiteralPath $setupWeb -Raw
    if ($setupText -match "throw") {
        Write-Check "setup_web.ps1" "OK" "disabled by design; do not treat throw as install failure"
    } else {
        Write-Check "setup_web.ps1" "WARN" "no longer fails closed"
    }
}

Write-Host ""
Write-Host "Doctor is read-only. It does not install packages, write data/, or use tokens."
Write-Host "Next: scripts/setup_windows.ps1 then scripts/run_tests_windows.ps1"
