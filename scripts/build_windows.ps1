param(
    [string]$Profile = "full",
    [switch]$BundlePythonRuntime,
    [switch]$SkipShortcut,
    [switch]$SkipSampleData
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$release = Join-Path $root "scripts\make_release.ps1"
if (-not (Test-Path -LiteralPath $release)) {
    throw "scripts/make_release.ps1 is missing."
}
$args = @("-Profile", $Profile)
if ($BundlePythonRuntime) { $args += "-BundlePythonRuntime" }
if ($SkipShortcut) { $args += "-SkipShortcut" }
if ($SkipSampleData) { $args += "-SkipSampleData" }
& $release @args
if ($LASTEXITCODE -ne 0) {
    throw "make_release.ps1 failed with exit code $LASTEXITCODE"
}
