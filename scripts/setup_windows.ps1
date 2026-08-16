param()

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$installer = Join-Path $root "INSTALL.bat"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "INSTALL.bat is missing."
}
$env:GALLERY_NONINTERACTIVE = "1"
$env:GALLERY_SKIP_LAUNCH = "1"
Set-Location $root
cmd.exe /d /c "`"$installer`""
if ($LASTEXITCODE -ne 0) {
    throw "INSTALL.bat failed with exit code $LASTEXITCODE"
}
