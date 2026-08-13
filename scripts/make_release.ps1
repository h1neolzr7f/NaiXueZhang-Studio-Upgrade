param(
    [string]$ReleaseRoot = "",
    [string]$PackageName = "pixiv-nai-gallery",
    [ValidateSet("full", "core")]
    [string]$Profile = "full",
    [ValidateRange(1, 8192)]
    [int]$SampleDataMiB = 384,
    [ValidateRange(1, 8192)]
    [int]$MinimumSampleDataMiB = 288,
    [switch]$SkipSampleData = $true,
    [switch]$AllowUnfilteredSampleContent,
    [switch]$SkipZip,
    [switch]$SkipShortcut,
    [switch]$ForceOverwrite,
    [switch]$BundlePythonRuntime,
    [switch]$AllowDirtySource,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# 缓存版本戳是内容哈希（scripts/asset_versions.py 维护）。发布前必须新鲜，
# 否则打出来的包带着过期戳，用户浏览器会拿到旧缓存资源。
# Python 解释器只解析一次：优先 -PythonExe，其次 .venv，最后 PATH。
# 找不到解释器时直接失败——后续构建/校验步骤同样依赖它，绝不能静默跳过打戳检查。
$assetVersioner = Join-Path $projectRoot "scripts\asset_versions.py"
$releasePython = ""
$pythonCandidates = @()
if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
    $pythonCandidates += $PythonExe
}
$pythonCandidates += (Join-Path $projectRoot ".venv\Scripts\python.exe")
foreach ($pythonCandidate in $pythonCandidates) {
    if (Test-Path -LiteralPath $pythonCandidate) {
        $releasePython = (Resolve-Path -LiteralPath $pythonCandidate).Path
        break
    }
}
if ([string]::IsNullOrWhiteSpace($releasePython)) {
    $pythonCommand = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pythonCommand) {
        $releasePython = $pythonCommand.Path
    }
}
if ([string]::IsNullOrWhiteSpace($releasePython)) {
    throw "Python is required to verify asset stamps and build the release (no .venv\Scripts\python.exe and no python.exe on PATH)."
}
if (Test-Path -LiteralPath $assetVersioner) {
    & $releasePython $assetVersioner --check | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Asset cache-bust stamps are stale. Run ``python scripts\asset_versions.py`` and commit the result before releasing."
    }
}
if (-not $AllowDirtySource) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".git"))) {
        throw "Source is not a Git checkout. Refusing an uncontrolled release build."
    }
    $gitTop = (& git -C $projectRoot rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($gitTop)) {
        throw "Source is not a Git checkout. Refusing an uncontrolled release build."
    }
    $gitStatus = @(& git -C $projectRoot status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $gitStatus.Count -gt 0) {
        throw "Source Git checkout has uncommitted or uncontrolled files."
    }
}
if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
    $ReleaseRoot = Join-Path (Split-Path -Parent $projectRoot) "releases"
}

function Test-SafePackageName([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name -ne $Name.Trim()) {
        return $false
    }
    if (
        [System.IO.Path]::IsPathRooted($Name) -or
        [System.IO.Path]::GetFileName($Name) -ne $Name -or
        $Name -in @(".", "..") -or
        $Name.EndsWith(".") -or
        $Name.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0 -or
        $Name -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$'
    ) {
        return $false
    }
    return $true
}

if (-not (Test-SafePackageName $PackageName)) {
    throw "PackageName must be a single safe directory name: $PackageName"
}
if (-not $SkipSampleData -and $MinimumSampleDataMiB -gt $SampleDataMiB) {
    throw "MinimumSampleDataMiB cannot exceed SampleDataMiB."
}
if ($Profile -eq "core" -and -not $SkipSampleData) {
    throw "Core releases cannot include crawled or sample image data."
}
if ($AllowUnfilteredSampleContent -and $SkipSampleData) {
    throw "AllowUnfilteredSampleContent requires sample data to be enabled."
}
function Resolve-ReleaseRoot([string]$Path) {
    $normalized = $Path.Trim().TrimEnd('\')
    if ($normalized -match '^[A-Za-z]:$') {
        $normalized = Join-Path $normalized "Packages"
        Write-Host "ReleaseRoot was a drive root; using $normalized"
    }
    if (-not (Test-Path -LiteralPath $normalized)) {
        New-Item -ItemType Directory -Path $normalized -Force | Out-Null
    }
    return (Resolve-Path -LiteralPath $normalized).Path
}

function ConvertTo-CanonicalPath([string]$Path) {
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $pathRoot = [System.IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.Equals($pathRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $fullPath
    }
    return $fullPath.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
}

function Test-PathIsSameOrDescendant([string]$Candidate, [string]$Container) {
    $canonicalCandidate = ConvertTo-CanonicalPath $Candidate
    $canonicalContainer = ConvertTo-CanonicalPath $Container
    if ($canonicalCandidate.Equals($canonicalContainer, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $containerPrefix = $canonicalContainer
    if (-not $containerPrefix.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $containerPrefix += [System.IO.Path]::DirectorySeparatorChar
    }
    return $canonicalCandidate.StartsWith($containerPrefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Install-UpperBat([string]$SourcePath, [string]$DestDir, [string]$DestName) {
    if (-not (Test-Path -LiteralPath $SourcePath)) {
        return
    }
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    $destPath = Join-Path $DestDir $DestName
    Get-ChildItem -LiteralPath $DestDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name.Equals($DestName, [System.StringComparison]::OrdinalIgnoreCase) } |
        Remove-Item -Force
    $bytes = [System.IO.File]::ReadAllBytes($SourcePath)
    [System.IO.File]::WriteAllBytes($destPath, $bytes)
}

$releaseRoot = Resolve-ReleaseRoot $ReleaseRoot
$finalStage = Join-Path $releaseRoot $PackageName
$zipPath = Join-Path $releaseRoot "$PackageName.zip"
$stageMarkerName = ".pixiv-nai-release-stage"
$stageMarkerValue = "pixiv-nai-gallery-release-v1"
$buildStage = Join-Path $releaseRoot ".$PackageName.build-$PID-$([Guid]::NewGuid().ToString('N'))"
$zipBuildPath = Join-Path $releaseRoot ".$PackageName.zip.build-$PID-$([Guid]::NewGuid().ToString('N')).tmp"
$stage = $buildStage

$canonicalProjectRoot = ConvertTo-CanonicalPath $projectRoot
$canonicalReleaseRoot = ConvertTo-CanonicalPath $releaseRoot
$canonicalStage = ConvertTo-CanonicalPath $finalStage
if (
    (Test-PathIsSameOrDescendant $canonicalStage $canonicalProjectRoot) -or
    (Test-PathIsSameOrDescendant $canonicalProjectRoot $canonicalStage)
) {
    throw "Release stage must be separate from the project source: $canonicalStage"
}
if (
    $canonicalStage.Equals($canonicalReleaseRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not (Test-PathIsSameOrDescendant $canonicalStage $canonicalReleaseRoot)
) {
    throw "Release stage must stay inside ReleaseRoot: $canonicalStage"
}

$existingStageOwned = $false
if (Test-Path -LiteralPath $finalStage) {
    $existingMarker = Join-Path $finalStage $stageMarkerName
    if (Test-Path -LiteralPath $existingMarker) {
        $existingStageOwned = (
            (Get-Content -LiteralPath $existingMarker -Raw -ErrorAction SilentlyContinue).Trim() -eq
            $stageMarkerValue
        )
    }
    if (-not $existingStageOwned -and -not $ForceOverwrite) {
        throw "Refusing to replace unowned release stage: $finalStage"
    }
}
if (
    -not $SkipZip -and
    (Test-Path -LiteralPath $zipPath) -and
    -not ($existingStageOwned -or $ForceOverwrite)
) {
    throw "Refusing to replace an unowned release zip: $zipPath"
}

$buildStageCreated = $false
trap {
    if ($buildStageCreated -and (Test-Path -LiteralPath $buildStage)) {
        Remove-Item -LiteralPath $buildStage -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($zipBuildPath -and (Test-Path -LiteralPath $zipBuildPath)) {
        Remove-Item -LiteralPath $zipBuildPath -Force -ErrorAction SilentlyContinue
    }
    throw $_
}

function Copy-FileRel([string]$RelativePath, [switch]$Required) {
    $src = Join-Path $projectRoot $RelativePath
    $dst = Join-Path $stage $RelativePath
    if (-not (Test-Path -LiteralPath $src)) {
        if ($Required) {
            throw "Required release source is missing: $RelativePath"
        }
        return
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Force
}

function Copy-DirRel([string]$RelativePath) {
    $src = Join-Path $projectRoot $RelativePath
    $dst = Join-Path $stage $RelativePath
    if (-not (Test-Path -LiteralPath $src)) {
        return
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
}

function Update-SampleDatabaseManifest([string]$StagePath) {
    $databasePath = Join-Path $StagePath "data\aitag.db"
    $manifestPath = Join-Path $StagePath "data\sample_manifest.json"
    if (-not (Test-Path -LiteralPath $databasePath) -or -not (Test-Path -LiteralPath $manifestPath)) {
        throw "Sample database or manifest is missing while finalizing its hash."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest.database_sha256 = (Get-FileHash -LiteralPath $databasePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest.database_bytes = (Get-Item -LiteralPath $databasePath).Length
    $manifestJson = $manifest | ConvertTo-Json -Depth 16
    [System.IO.File]::WriteAllText(
        $manifestPath,
        $manifestJson + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Write-SeedManifest([string]$StagePath, [string]$ReleaseProfile) {
    $seedFiles = if ($ReleaseProfile -eq "core") {
        @("data\char_tag_index.json", "data\danbooru_creature.json")
    } else {
        @(
            "data\ark_char_library.json",
            "data\butler_catalog.json",
            "data\char_presets.json",
            "data\char_tag_index.json",
            "data\danbooru_arknights.json",
            "data\danbooru_creature.json",
            "data\danbooru_recognition.json",
            "data\danbooru_style_tags.json",
            "data\director_catalog.json",
            "data\pixiv_upload_selectors.json"
        )
    }
    $entries = @(
        foreach ($relative in $seedFiles) {
            $asset = Join-Path $StagePath $relative
            if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
                throw "Starter-library asset is missing: $relative"
            }
            [pscustomobject][ordered]@{
                path = $relative.Replace('\', '/')
                bytes = [long](Get-Item -LiteralPath $asset).Length
                sha256 = (Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    )
    $manifest = [ordered]@{
        schema_version = 1
        release_profile = $ReleaseProfile
        generation_calls = 0
        files = $entries
    }
    $manifestPath = Join-Path $StagePath "data\seed_manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
}

New-Item -ItemType Directory -Path $stage -Force | Out-Null
$buildStageCreated = $true
$oneClickZhName = (-join @([char]0x4E00, [char]0x952E, [char]0x542F, [char]0x52A8)) + ".bat"
$manualZhName = (-join @([char]0x4F7F, [char]0x7528, [char]0x8BF4, [char]0x660E)) + ".txt"

$fullRootFiles = @(
    ".gitignore",
    "INSTALL.bat",
    "ONE_CLICK_START.bat",
    "BACKUP_GALLERY.bat",
    "RESTORE_GALLERY.bat",
    "LICENSE",
    "VERSION",
    "THIRD_PARTY_NOTICES.md",
    "ark_char_library.py",
    "ark_stats.py",
    "BUNDLE_NOTICE.txt",
    "char_marker.py",
    "char_swap_config.py",
    "char_tag_db.py",
    "config.release.json",
    "crawler.py",
    "crawler_control.py",
    "crawler_task.py",
    "crawler_watchdog.py",
    "db.py",
    "db_compression.py",
    "db_queries.py",
    "favorites.py",
    "gallery_audit_service.py",
    "gallery_cache.py",
    "gallery_catalog.py",
    "gallery_asset_store.py",
    "gallery_maintenance.py",
    "gallery_snapshot.py",
    "generated_gallery.py",
    "Get-Pixiv-Token.bat",
    "nai_api.py",
    "nai_anima_adapter.py",
    "nai_batch.py",
    "nai_char.py",
    "nai_director.py",
    "nai_image_metadata.py",
    "nai_prompt_optimizer.py",
    "nai_prompt_profiles.py",
    "nai_prompt_tags.py",
    "nai_tag_index.py",
    "paths.py",
    "server_shared.py",
    "studio_service.py",
    "user_prefs.py",
    "pixiv_accounts.py",
    "pixiv_browser_login.py",
    "pixiv_browser_source.py",
    "pixiv_public_source.py",
    "pixiv_char_tags.py",
    "pixiv_launch.py",
    "pixiv_launch_config.py",
    "pixiv_launch_tags.py",
    "pixiv_ai_transport.py",
    "pixiv_nai_crawler.py",
    "pixiv_nai_intake.py",
    "pixiv_nai_preflight.py",
    "pixiv_nai_source.py",
    "pixiv_web_upload.py",
    "post_pipeline.py",
    "product_ops.py",
    "production_queue.py",
    "progress.py",
    "README.md",
    "reindex_fts.py",
    "requirements.lock.txt",
    "requirements.txt",
    "run_crawl_background.ps1",
    "search.py",
    "server.py",
    "atomic_io.py",
    "butler_gallery_operations.py",
    "butler_service.py",
    "butler_templates.py",
    "crawler_hub.py",
    "crawler_qq.py",
    "db_crawler_writes.py",
    "db_prompt_index.py",
    "generation_jobs.py",
    "knowledge_catalog.py",
    "local_secrets.py",
    "qq_gallery_ingest.py",
    "reference_catalog.py",
    "runtime_resources.py",
    "setup_web.ps1",
    "software_help.py",
    "usage_ledger.py",
    "work_refs.py",
    "CREATE_DESKTOP_SHORTCUT.bat",
    "start_gallery.ps1",
    "start_crawl.bat",
    "start_crawl.ps1",
    "start_crawl_local.bat",
    "start_crawl_all.bat",
    "start_crawl_qq.bat",
    "start_crawl_site.bat",
    "slot_gender.py",
    "static_asset_security.py",
    "status.py",
    "tag_translate.py"
)
$coreRootFiles = @(
    ".gitignore",
    "INSTALL.bat",
    "ONE_CLICK_START.bat",
    "LICENSE",
    "VERSION",
    "THIRD_PARTY_NOTICES.md",
    "BUNDLE_NOTICE.txt",
    "config.release.json",
    "README.md",
    "BACKUP_GALLERY.bat",
    "RESTORE_GALLERY.bat",
    "CREATE_DESKTOP_SHORTCUT.bat",
    "start_gallery.ps1",
    "START_GALLERY.bat",
    "setup_web.ps1",
    "atomic_io.py",
    "char_tag_db.py",
    "db.py",
    "db_compression.py",
    "db_crawler_writes.py",
    "db_prompt_index.py",
    "db_queries.py",
    "gallery_asset_store.py",
    "gallery_maintenance.py",
    "gallery_snapshot.py",
    "local_secrets.py",
    "nai_image_metadata.py",
    "nai_prompt_tags.py",
    "nai_tag_index.py",
    "paths.py",
    "pixiv_nai_crawler.py",
    "pixiv_nai_intake.py",
    "pixiv_nai_preflight.py",
    "pixiv_nai_source.py",
    "pixiv_browser_source.py",
    "pixiv_public_source.py",
    "search.py",
    "server_shared.py"
)
$rootFiles = if ($Profile -eq "core") { $coreRootFiles } else { $fullRootFiles }
foreach ($file in $rootFiles) {
    Copy-FileRel $file
}
foreach ($file in @($oneClickZhName, $manualZhName)) {
    Copy-FileRel $file
}
if ($Profile -eq "core") {
    Copy-Item -LiteralPath (Join-Path $projectRoot "requirements.core.txt") `
        -Destination (Join-Path $stage "requirements.txt") -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "requirements.core.lock.txt") `
        -Destination (Join-Path $stage "requirements.lock.txt") -Force
}
$releaseConfig = Join-Path $stage "config.release.json"
if (-not (Test-Path -LiteralPath $releaseConfig)) {
    throw "Release config is missing: $releaseConfig"
}
Copy-Item -LiteralPath $releaseConfig -Destination (Join-Path $stage "config.json") -Force

Install-UpperBat (Join-Path $projectRoot "start_gallery.bat") $stage "START_GALLERY.bat"
if ($Profile -eq "core") {
    $coreServerTemplate = Join-Path $projectRoot "scripts\server_core.py"
    if (-not (Test-Path -LiteralPath $coreServerTemplate)) {
        throw "Core server template is missing: $coreServerTemplate"
    }
    Copy-Item -LiteralPath $coreServerTemplate -Destination (Join-Path $stage "server.py") -Force
    foreach ($template in @(
        @{ Source = "scripts\crawler_control_core.py"; Destination = "crawler_control.py" },
        @{ Source = "scripts\pixiv_accounts_core.py"; Destination = "pixiv_accounts.py" },
        @{ Source = "scripts\routes_gallery_core.py"; Destination = "routes\gallery.py" },
        @{ Source = "scripts\routes_nai_tags_core.py"; Destination = "routes\nai_tags.py" },
        @{ Source = "scripts\server_shared_core.py"; Destination = "server_shared.py" },
        @{ Source = "scripts\core_web_app.js"; Destination = "web\core-gallery.js" },
        @{ Source = "scripts\core_web_index.html"; Destination = "web\index.html" },
        @{ Source = "scripts\core_web_intake.js"; Destination = "web\core-intake.js" },
        @{ Source = "scripts\core_web_progress.html"; Destination = "web\progress.html" }
    )) {
        $templateSource = Join-Path $projectRoot $template.Source
        if (-not (Test-Path -LiteralPath $templateSource)) {
            throw "Core release template is missing: $templateSource"
        }
        $templateDestination = Join-Path $stage $template.Destination
        New-Item -ItemType Directory -Path (Split-Path -Parent $templateDestination) -Force | Out-Null
        Copy-Item -LiteralPath $templateSource -Destination $templateDestination -Force
    }
    foreach ($file in @(
        "routes\maintenance.py",
        "routes\pixiv_intake.py"
    )) {
        Copy-FileRel $file
    }
    Copy-DirRel "third_party"
    foreach ($file in @(
        "web\core-theme.css",
        "web\favicon.ico",
        "web\favicon.png",
        "web\gallery-maintenance.js",
        "web\maintenance.html",
        "web\nai-tags.html",
        "web\nai-tags.js",
        "web\pixiv-intake-control.js",
        "web\shared\api-client.js"
    )) {
        Copy-FileRel $file
    }
    foreach ($file in @(
        "scripts\create_desktop_shortcuts.ps1",
        "scripts\gallery_process_guard.ps1",
        "scripts\gallery_process_guard.py",
        "scripts\launch_server.vbs",
        "scripts\select_python_runtime.bat"
    )) {
        Copy-FileRel $file
    }
} else {
    Copy-DirRel "routes"
    Copy-DirRel "aitag_core"
    Copy-DirRel "nai_char_modules"
    Copy-DirRel "nai"
    Copy-DirRel "butler"
    Copy-DirRel "third_party"
    Copy-DirRel "web"
    Copy-DirRel "tests"
    Copy-DirRel "scripts"
}
Remove-Item -LiteralPath (Join-Path $stage "scripts\make_release.ps1") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "scripts\scan_sensitive.py") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "scripts\generate_user_manual_docx.py") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "scripts\logs") -Recurse -Force -ErrorAction SilentlyContinue
# 备份产物清扫覆盖整个 stage（不只 web）：tests/routes/scripts 里同样可能
# 存在 .bak-* 文件；备份目录（如 xxx.backup-20260811/）整体移除。
Get-ChildItem -LiteralPath $stage -Recurse -Force -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '(?i)(?:^|[._-])(?:bak|backup)(?:[._-]|$)' } |
    Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $stage -Recurse -Force -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '(?i)(?:^|[._-])(?:bak|backup)(?:[._-]|$)' } |
    Sort-Object { $_.FullName.Length } -Descending |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $stage -Recurse -Force -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "__pycache__" } |
    Sort-Object { $_.FullName.Length } -Descending |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $stage -Recurse -Force -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

$fullDataFiles = @(
    "data\ark_char_library.json",
    "data\butler_catalog.json",
    "data\char_presets.json",
    "data\char_tag_groups.json",
    "data\char_tag_index.json",
    "data\danbooru_arknights.json",
    "data\danbooru_creature.json",
    "data\danbooru_recognition.json",
    "data\danbooru_style_tags.json",
    "data\director_catalog.json",
    "data\sanitize_blocklist.json",
    "data\tag_dict.json",
    "data\nai_token.local.example.json",
    "data\pixiv_accounts.local.example.json",
    "data\pixiv_upload_selectors.json",
    "data\ai.local.example.json"
)
$coreDataFiles = @(
    "data\char_tag_groups.json",
    "data\char_tag_index.json",
    "data\danbooru_creature.json"
)
$dataFiles = if ($Profile -eq "core") { $coreDataFiles } else { $fullDataFiles }
foreach ($file in $dataFiles) {
    # 种子/示例数据是运行必需的：源缺失必须让发布失败，不能静默跳过。
    Copy-FileRel $file -Required
}
Write-SeedManifest -StagePath $stage -ReleaseProfile $Profile

if ($Profile -ne "core") {
    Copy-FileRel "data\pixiv_launch.sample.json"
    Copy-Item -LiteralPath (Join-Path $projectRoot "data\pixiv_launch.sample.json") -Destination (Join-Path $stage "data\pixiv_launch.json") -Force
    Copy-FileRel "data\post_pipeline.sample.json"
    Copy-Item -LiteralPath (Join-Path $projectRoot "data\post_pipeline.sample.json") -Destination (Join-Path $stage "data\post_pipeline.json") -Force
}

if ($SkipSampleData) {
    New-Item -ItemType Directory -Path (Join-Path $stage "data\images") -Force | Out-Null
} else {
    $sampleBuilder = Join-Path $projectRoot "scripts\build_sample_gallery.py"
    $sampleArgs = @(
        $sampleBuilder,
        "--source-db", (Join-Path $projectRoot "data\aitag.db"),
        "--source-data", (Join-Path $projectRoot "data"),
        "--output-data", (Join-Path $stage "data"),
        "--target-mib", $SampleDataMiB,
        "--minimum-mib", $MinimumSampleDataMiB
    )
    if ($AllowUnfilteredSampleContent) {
        $sampleArgs += "--allow-unfiltered-content"
    }
    & $releasePython @sampleArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Sample Gallery Work export failed with exit code $LASTEXITCODE."
    }
}
if ($Profile -ne "core") {
    New-Item -ItemType Directory -Path (Join-Path $stage "data\generated") -Force | Out-Null
}
New-Item -ItemType Directory -Path (Join-Path $stage "logs") -Force | Out-Null

$forbiddenNames = @(
    "char_swap_config.json",
    "nai_token.local.json",
    "pixiv.local.json",
    "pixiv_accounts.local.json",
    "pixiv_accounts.local.backup.json",
    "pixiv_nai_task.local.json",
    "pixiv_nai_state.local.json",
    "pixiv_nai_report.local.json",
    ".pixiv-credentials.lock",
    "ai.local.json",
    "butler_state.db",
    "favorites.json",
    "generation_jobs.json",
    "user_prefs.json",
    "_cookies_tmp.db"
)
$forbiddenFound = @()
foreach ($name in $forbiddenNames) {
    $hits = Get-ChildItem -LiteralPath $stage -Recurse -Force -File -Filter $name -ErrorAction SilentlyContinue
    if ($hits) {
        $forbiddenFound += $hits.FullName
    }
}
if ($forbiddenFound.Count -gt 0) {
    throw "Forbidden private files found in release stage:`n$($forbiddenFound -join "`n")"
}

$scanPatterns = @(
    '(?i)\bsk-[A-Za-z0-9_-]{32,}\b',
    '(?i)\bpst-[A-Za-z0-9_-]{48,}\b',
    '(?i)"refresh_token"\s*:\s*"[A-Za-z0-9._~-]{48,}"',
    '(?i)"api_key"\s*:\s*"[A-Za-z0-9._-]{32,}"'
)
$knownTestPlaceholders = @(
    "sk-abcdefghijklmnopqrstuvwxyz123456"
)
$textFiles = Get-ChildItem -LiteralPath $stage -Recurse -Force -File |
    Where-Object {
        $_.Length -lt 209715200 -and
        $_.FullName -notmatch "\\data\\images\\" -and
        $_.Name -notmatch "\.example\.json$" -and
        $_.FullName -notmatch "\\scripts\\migrate_" -and
        $_.Extension -notin @(".db", ".png", ".webp", ".ico", ".zip")
    }
$sensitiveHits = @()
foreach ($file in $textFiles) {
    $content = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    foreach ($placeholder in $knownTestPlaceholders) {
        $content = $content.Replace($placeholder, "known-test-placeholder")
    }
    foreach ($pat in $scanPatterns) {
        if ($content -match $pat) {
            $sensitiveHits += "$($file.FullName) contains $pat"
        }
    }
}
if ($sensitiveHits.Count -gt 0) {
    throw "Sensitive-looking content found:`n$($sensitiveHits -join "`n")"
}

if ($Profile -ne "core") {
    $releasePixivCfg = Get-Content -LiteralPath (Join-Path $stage "data\pixiv_launch.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($releasePixivCfg.ai.provider -or $releasePixivCfg.ai.api_base -or $releasePixivCfg.ai.model) {
        throw "Release pixiv_launch.json must not include a default AI provider/api_base/model."
    }
}

$releaseCfg = Get-Content -LiteralPath (Join-Path $stage "config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$releaseCfg.base_url -or [string]$releaseCfg.cdn_url) {
    throw "Release config must not depend on the legacy upstream or CDN."
}
if ([bool]$releaseCfg.legacy_aitag_crawler_enabled) {
    throw "Legacy upstream crawler must stay disabled in the release."
}

if ($BundlePythonRuntime) {
    Set-Content -LiteralPath (Join-Path $stage $stageMarkerName) -Value $stageMarkerValue -Encoding ASCII
    $runtimeBuilder = Join-Path $projectRoot "scripts\build_portable_runtime.ps1"
    & $runtimeBuilder `
        -PackageRoot $stage `
        -PythonExe $releasePython `
        -Profile $Profile `
        -BrowserMode "system"
    if ($LASTEXITCODE -ne 0) {
        throw "Portable Python runtime build failed with exit code $LASTEXITCODE."
    }
}

$gitCommit = "unknown"
$gitDirty = $true
if (Test-Path -LiteralPath (Join-Path $projectRoot ".git")) {
    $gitCommitCandidate = (& git -C $projectRoot rev-parse HEAD)
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($gitCommitCandidate)) {
        $gitCommit = ([string]$gitCommitCandidate).Trim()
    }
    $gitStatus = @(& git -C $projectRoot status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -eq 0) {
        $gitDirty = $gitStatus.Count -gt 0
    }
}
Get-ChildItem -LiteralPath $stage -Recurse -Force -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "__pycache__" } |
    Sort-Object { $_.FullName.Length } -Descending |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $stage -Recurse -Force -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "data\aitag.db-shm") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "data\aitag.db-wal") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "data\cache") -Recurse -Force -ErrorAction SilentlyContinue

if (-not $SkipSampleData) {
    Update-SampleDatabaseManifest -StagePath $stage
}

Set-Content -LiteralPath (Join-Path $stage $stageMarkerName) -Value $stageMarkerValue -Encoding ASCII

$stageFiles = @(
    Get-ChildItem -LiteralPath $stage -Recurse -Force -File |
        Where-Object { $_.Name -ne "release_manifest.json" }
)
$releaseInventory = @(
    foreach ($file in $stageFiles) {
        # Windows PowerShell 5.1 runs on .NET Framework, which does not expose
        # Path.GetRelativePath. Every inventory file is already enumerated
        # beneath $stage, so a checked prefix trim is portable and unambiguous.
        $relativePath = $file.FullName.Substring($stage.Length).TrimStart([char[]]@([char]92, [char]47)).Replace('\', '/')
        [pscustomobject][ordered]@{
            path = $relativePath
            bytes = [long]$file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
)
$stageBytes = ($releaseInventory | Measure-Object -Property bytes -Sum).Sum
$releaseManifest = [ordered]@{
    schema_version = 2
    package_name = $PackageName
    release_profile = $Profile
    artifact_kind = if ($BundlePythonRuntime) { "windows_portable_one_click" } elseif ($Profile -eq "core") { "open_source_core" } else { "beginner_bundle_version_backup" }
    source_commit = ([string]$gitCommit).Trim()
    source_worktree_dirty = [bool]$gitDirty
    created_at = [DateTimeOffset]::Now.ToString("o")
    sample_data_mib_target = if ($SkipSampleData) { 0 } else { $SampleDataMiB }
    sample_content_filter_enabled = if ($SkipSampleData) { $null } else { -not [bool]$AllowUnfilteredSampleContent }
    private_runtime_state_included = $false
    install_entrypoint = "INSTALL.bat"
    start_entrypoint = if ($BundlePythonRuntime) { $oneClickZhName } else { "START_GALLERY.bat" }
    portable_runtime_included = [bool]$BundlePythonRuntime
    browser_mode = if ($BundlePythonRuntime) { "system_chrome_or_edge" } else { "not_applicable" }
    inventory_algorithm = "sha256"
    inventory = $releaseInventory
    file_count = $stageFiles.Count
    bytes = [long]$stageBytes
}
$releaseManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stage "release_manifest.json") -Encoding UTF8

$stageVerifier = Join-Path $projectRoot "scripts\verify_release_stage.py"
$verifyArgs = @($stageVerifier, $stage)
if ($SkipSampleData) {
    $verifyArgs += "--allow-empty-sample"
}
$previousDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $releasePython @verifyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Release stage smoke verification failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($null -eq $previousDontWriteBytecode) {
        Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONDONTWRITEBYTECODE = $previousDontWriteBytecode
    }
}
Get-ChildItem -LiteralPath $stage -Recurse -Force -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "__pycache__" } |
    Sort-Object { $_.FullName.Length } -Descending |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $stage -Recurse -Force -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "data\aitag.db-shm") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "data\aitag.db-wal") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $stage "data\cache") -Recurse -Force -ErrorAction SilentlyContinue

if (-not $SkipZip) {
    $zipScript = Join-Path $projectRoot "scripts\zip_release.py"
    $zipArgs = @($zipScript, $buildStage, $zipBuildPath, "--root-name", $PackageName)
    if (-not $BundlePythonRuntime) {
        $zipArgs += "--stored"
    }
    & $releasePython @zipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Release zip creation failed with exit code $LASTEXITCODE."
    }
    $reportedZip = $zipPath
} else {
    Write-Host "SkipZip set; folder package only."
    $reportedZip = "(skipped; existing zip left untouched)"
}

$previousStageBackup = $null
$previousZipBackup = $null
# 回滚面：发布成功后保留恰好一份上一版 stage，固定名为 .<PackageName>.previous，
# 替换掉更早的回滚副本；需要回滚时把它改名回 $PackageName 即可。
$rollbackStage = Join-Path $releaseRoot ".$PackageName.previous"
if (Test-Path -LiteralPath $finalStage) {
    $previousStageBackup = Join-Path $releaseRoot ".$PackageName.previous-$PID-$([Guid]::NewGuid().ToString('N'))"
    Move-Item -LiteralPath $finalStage -Destination $previousStageBackup
}
if (-not $SkipZip -and (Test-Path -LiteralPath $zipPath)) {
    $previousZipBackup = Join-Path $releaseRoot ".$PackageName.zip.previous-$PID-$([Guid]::NewGuid().ToString('N'))"
    Move-Item -LiteralPath $zipPath -Destination $previousZipBackup
}
try {
    Move-Item -LiteralPath $buildStage -Destination $finalStage
    $buildStageCreated = $false
    if (-not $SkipZip) {
        Move-Item -LiteralPath $zipBuildPath -Destination $zipPath
    }
} catch {
    if (Test-Path -LiteralPath $finalStage) {
        Remove-Item -LiteralPath $finalStage -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($previousStageBackup -and (Test-Path -LiteralPath $previousStageBackup)) {
        Move-Item -LiteralPath $previousStageBackup -Destination $finalStage -ErrorAction SilentlyContinue
    }
    if (-not $SkipZip -and (Test-Path -LiteralPath $zipPath)) {
        Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
    }
    if ($previousZipBackup -and (Test-Path -LiteralPath $previousZipBackup)) {
        Move-Item -LiteralPath $previousZipBackup -Destination $zipPath -ErrorAction SilentlyContinue
    }
    throw
}
if ($previousStageBackup -and (Test-Path -LiteralPath $previousStageBackup)) {
    if (Test-Path -LiteralPath $rollbackStage) {
        Remove-Item -LiteralPath $rollbackStage -Recurse -Force
    }
    Move-Item -LiteralPath $previousStageBackup -Destination $rollbackStage
}
if ($previousZipBackup -and (Test-Path -LiteralPath $previousZipBackup)) {
    Remove-Item -LiteralPath $previousZipBackup -Force
}
$stage = $finalStage

if (-not $SkipShortcut) {
    $shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Pixiv NAI Gallery.lnk"
    $wsh = New-Object -ComObject WScript.Shell
    $link = $wsh.CreateShortcut($shortcut)
    $link.TargetPath = Join-Path $stage "START_GALLERY.bat"
    $link.WorkingDirectory = $stage
    $icon = Join-Path $stage "web\favicon.ico"
    if (Test-Path -LiteralPath $icon) {
        $link.IconLocation = $icon
    }
    $link.Description = "Start Pixiv NAI Gallery"
    $link.Save()
} else {
    $shortcut = "(skipped)"
}

Write-Host "Release folder: $stage"
Write-Host "Release zip:    $reportedZip"
Write-Host "Shortcut:       $shortcut"
