[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,

    [string]$PythonExe = "",

    [ValidateSet("core", "full")]
    [string]$Profile = "core",

    [ValidateSet("system")]
    [string]$BrowserMode = "system"
)

$ErrorActionPreference = "Stop"

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($LiteralPath)
        try {
            return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
        } finally {
            $stream.Dispose()
        }
    } finally {
        $sha.Dispose()
    }
}

$package = (Resolve-Path -LiteralPath $PackageRoot).Path
$requirements = Join-Path $package "requirements.lock.txt"
$server = Join-Path $package "server.py"
$releaseMarker = Join-Path $package ".pixiv-nai-release-stage"
if (-not (Test-Path -LiteralPath $requirements)) {
    throw "Portable runtime requires requirements.lock.txt: $requirements"
}
if (-not (Test-Path -LiteralPath $server)) {
    throw "Portable runtime requires server.py: $server"
}
if (-not (Test-Path -LiteralPath $releaseMarker)) {
    throw "Portable runtime can only be added to an owned release stage: $package"
}

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "PythonExe is required when python.exe is not on PATH."
    }
    $PythonExe = $pythonCommand.Source
}
$python = (Resolve-Path -LiteralPath $PythonExe).Path
$infoJson = & $python -c "import json,platform,sys; print(json.dumps({'base_prefix':sys.base_prefix,'version':platform.python_version(),'bits':platform.architecture()[0]}))"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the build Python runtime."
}
$info = $infoJson | ConvertFrom-Json
if ([string]$info.bits -ne "64bit") {
    throw "The Windows portable bundle requires a 64-bit Python runtime."
}
$versionParts = ([string]$info.version).Split(".")
$minor = [int]$versionParts[1]
if ([int]$versionParts[0] -ne 3 -or $minor -ne 13) {
    throw "The Windows portable bundle requires CPython 3.13 x64. Found $($info.version)."
}
$base = (Resolve-Path -LiteralPath ([string]$info.base_prefix)).Path
$baseLib = Join-Path $base "Lib"
$baseDlls = Join-Path $base "DLLs"
if (-not (Test-Path -LiteralPath $baseLib) -or -not (Test-Path -LiteralPath $baseDlls)) {
    throw "The selected Python installation is missing Lib or DLLs: $base"
}

$runtime = Join-Path $package "runtime"
if (Test-Path -LiteralPath $runtime) {
    throw "Portable runtime already exists; build from a clean release stage: $runtime"
}
$runtimeBuild = Join-Path $package (".runtime.build-" + [Guid]::NewGuid().ToString("N"))
$runtimeBuildCanonical = [System.IO.Path]::GetFullPath($runtimeBuild)
$packageCanonical = [System.IO.Path]::GetFullPath($package).TrimEnd("\")
if (-not $runtimeBuildCanonical.StartsWith($packageCanonical + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe runtime build path: $runtimeBuildCanonical"
}

try {
    New-Item -ItemType Directory -Path $runtimeBuild -Force | Out-Null
    foreach ($name in @(
        "python.exe",
        "pythonw.exe",
        "python3.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "LICENSE.txt"
    )) {
        $source = Join-Path $base $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $runtimeBuild $name) -Force
        }
    }
    Get-ChildItem -LiteralPath $base -File -Filter "python3*.dll" |
        Where-Object { $_.Name -ne "python3.dll" } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $runtimeBuild -Force }
    Get-ChildItem -LiteralPath $base -File -Filter "python*.zip" |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $runtimeBuild -Force }

    $runtimeDlls = Join-Path $runtimeBuild "DLLs"
    $runtimeLib = Join-Path $runtimeBuild "Lib"
    New-Item -ItemType Directory -Path $runtimeDlls -Force | Out-Null
    New-Item -ItemType Directory -Path $runtimeLib -Force | Out-Null
    & robocopy.exe $baseDlls $runtimeDlls /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Could not copy Python DLLs; robocopy exit code $LASTEXITCODE."
    }
    & robocopy.exe $baseLib $runtimeLib /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP `
        /XD site-packages test tests tkinter idlelib ensurepip __pycache__ venv | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Could not copy the Python standard library; robocopy exit code $LASTEXITCODE."
    }

    $sitePackages = Join-Path $runtimeLib "site-packages"
    New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null
    & $python -m pip install `
        --disable-pip-version-check `
        --no-compile `
        --no-deps `
        --only-binary=:all: `
        --target $sitePackages `
        -r $requirements `
        -q
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install locked $Profile dependencies into the portable runtime."
    }

    Get-ChildItem -LiteralPath $runtimeBuild -Recurse -Force -Directory |
        Where-Object { $_.Name -in @("__pycache__", "test", "tests") } |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    Get-ChildItem -LiteralPath $runtimeBuild -Recurse -Force -File -Filter "*.pyc" |
        Remove-Item -Force -ErrorAction SilentlyContinue

    $runtimePython = Join-Path $runtimeBuild "python.exe"
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        throw "Portable python.exe was not created."
    }
    $validationCode = @"
import sys
sys.path.insert(0, sys.argv[1])
profile = sys.argv[2]
import aiofiles, fastapi, httpx, numpy, PIL, psutil, pydantic, uvicorn, yaml
if profile == 'full':
    import aiosqlite, cv2, gradio, langgraph, orjson, playwright, sqlite_vec
    import torch, torchvision, ultralytics
import server
route_paths = {getattr(route, 'path', '') for route in server.app.routes}
if profile == 'full':
    required_routes = {
        '/', '/studio', '/generated', '/director', '/butler', '/pixiv',
        '/settings', '/remix', '/progress', '/ops', '/tag-assets',
        '/pipeline', '/references', '/nai-tags', '/maintenance',
        '/api/config', '/api/generated', '/api/nai/status',
        '/api/director/catalog', '/api/butler/status',
        '/api/settings/status', '/api/studio/config', '/api/pixiv/config',
        '/api/product/health', '/api/nai/references',
        '/api/pipeline/status', '/api/crawler/pixiv/task',
        '/api/crawler/pixiv/report', '/api/nai-tags',
        '/api/maintenance/storage',
    }
else:
    required_routes = {
        '/', '/api/config', '/api/crawler/pixiv/task',
        '/api/crawler/pixiv/report', '/api/nai-tags', '/nai-tags',
    }
missing_routes = sorted(required_routes - route_paths)
assert not missing_routes, f'missing portable routes: {missing_routes}'
assert len(route_paths) >= (100 if profile == 'full' else 30)
print('portable-runtime-ok', profile, sys.version.split()[0], len(route_paths))
"@
    & $runtimePython -B -I -s -c $validationCode $package $Profile
    if ($LASTEXITCODE -ne 0) {
        throw "Portable runtime could not validate the $Profile server and route contract."
    }

    $manifest = [ordered]@{
        schema_version = 2
        profile = $Profile
        python_version = [string]$info.version
        architecture = [string]$info.bits
        requirements_file = "requirements.lock.txt"
        requirements_sha256 = Get-Sha256Hex -LiteralPath $requirements
        startup = "START_GALLERY.bat"
        self_contained = $true
        browser_mode = "system_chrome_or_edge"
        browser_runtime_included = $false
        browser_requirement = "Microsoft Edge or Google Chrome is required for Pixiv browser login and upload."
    }
    $manifest | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath (Join-Path $runtimeBuild "runtime_manifest.json") -Encoding UTF8
    Move-Item -LiteralPath $runtimeBuild -Destination $runtime
    Write-Host "Portable runtime: $runtime"
} catch {
    if (Test-Path -LiteralPath $runtimeBuild) {
        Remove-Item -LiteralPath $runtimeBuild -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
