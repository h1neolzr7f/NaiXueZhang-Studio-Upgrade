param(
    [switch]$SkipBrowserTests
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$verify = Join-Path $root "scripts\verify.ps1"
if (-not (Test-Path -LiteralPath $verify)) {
    throw "scripts/verify.ps1 is missing."
}
$args = @()
if ($SkipBrowserTests) { $args += "-SkipBrowserTests" }
& $verify @args
if ($LASTEXITCODE -ne 0) {
    throw "verify.ps1 failed with exit code $LASTEXITCODE"
}
