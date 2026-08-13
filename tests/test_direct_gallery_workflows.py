import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_small_mirror_and_character_swap_stay_in_primary_nav():
    nav = read("web/shared/site-nav.js")
    primary = nav.split("const NAV_SECONDARY", 1)[0]
    assert '{ href: "/app/butler", id: "butler", label: "小镜" }' in primary
    assert '{ href: "/app/remix", id: "remix", label: "换角" }' in primary


def test_gallery_switch_is_visible_and_race_guarded():
    html = read("web/index.html")
    app = read("web/app.js")
    assert 'class="gallery-source-bar"' in html
    assert all(f'data-gallery-source="{gid}"' in html for gid in ("site", "codex", "qqgroup"))
    assert "galleryRequestGeneration" in app
    assert "requestGeneration !== galleryRequestGeneration" in app
    assert "selected !== currentGalleryId()" in app


def test_detail_character_swap_prefers_existing_panel_over_navigation():
    # app.js 已按域拆分：详情视图动作在 app-detail.js
    app = read("web/app-detail.js")
    handler = app.split("document.getElementById('detailToRemixBtn')", 1)[1].split("detailQueueBtn", 1)[0]
    assert "focusCharSwapPanel" in handler
    assert "loadCharSwapPlugin" in handler
    assert "await plugin.mountDetail(workId, data)" in handler
    assert handler.index("focusCharSwapPanel") < handler.index("WorkBridge.go('/remix'")


def test_char_swap_mount_preserves_gallery_and_large_work_ids():
    plugin = read("web/plugins/char-swap/plugin.js")
    mount = plugin.split("async _mountPanel", 1)[1].split("const cfg =", 1)[0]
    # _mountPanel 内联清理旧面板/计时器/缓存而不是调 this.unmount()：
    # unmount() 会 bump _mountGeneration，把本次挂载误判为过期。
    assert "const gen = ++_mountGeneration" in mount
    assert 'document.getElementById("charSwapPanel")' in mount
    assert "unmountGenSidebar()" in mount
    assert "extractCache.clear()" in mount
    assert "state.galleryId = preservedGalleryId" in mount
    assert "normalizeWorkId(workId)" in plugin
    assert "Number(workId)" not in plugin


def test_all_transform_paths_carry_gallery_context():
    panel = read("web/plugins/char-swap/panel.js")
    assert "export function activeGalleryId" in panel
    assert panel.count("gallery_id: activeGalleryId") >= 2
    assert "const gid = activeGalleryId(body.gallery_id)" in panel
    assert "gallery_id: gid" in panel


def test_draft_cache_is_isolated_by_gallery():
    state = read("web/plugins/char-swap/state.js")
    assert 'const DRAFT_CACHE_KEY = "charSwapDraftPageCache.v8"' in state
    assert '"charSwapDraftPageCache.v7"' in state
    assert 'return `${normalizeGalleryId(galleryId)}:${normalizeWorkId(workId)}:${Number(pageIndex || 0)}`' in state
    assert 'const prefix = `${normalizeGalleryId(galleryId)}:${id}:`' in state


def test_async_mount_and_cache_versions_are_consistent():
    remix = read("web/remix.js")
    hooks = read("web/shared/gallery-detail-hooks.js")
    plugin = read("web/plugins/char-swap/plugin.js")
    panel = read("web/plugins/char-swap/panel.js")
    presets = read("web/plugins/char-swap/presets.js")
    index = read("web/index.html")
    assert "await plugin.mountRemix" in remix
    assert "await plugin.mountDetail" in hooks
    assert "{ throwOnError: true }" in plugin
    assert "if (options.throwOnError) throw e" in panel
    assert "cacheVersion: 6" not in presets
    # remix/hooks 必须引用同一插件版本；版本戳为内容哈希，由 asset_versions.py 维护
    remix_ver = re.search(r"plugin\.js\?v=([0-9a-f]+)", remix)
    hooks_ver = re.search(r"plugin\.js\?v=([0-9a-f]+)", hooks)
    assert remix_ver and hooks_ver
    assert remix_ver.group(1) == hooks_ver.group(1)
    assert re.search(r'PLUGIN_VERSION = "\d+-', plugin)
    assert re.search(r"gallery-detail-hooks\.js\?v=[0-9a-f]+", index)


def test_remix_keeps_large_ids_without_a_duplicate_recent_picker():
    html = read("web/remix.html")
    remix = read("web/remix.js")
    assert 'type="text" inputmode="numeric"' in html
    assert "remixRecentPicker" not in remix
    assert "loadRecentWorksPicker" not in remix
    assert "/api/ai_works_search" not in remix


def test_remix_manual_loader_is_keyboard_safe_and_keeps_current_context():
    html = read("web/remix.html")
    remix = read("web/remix.js")
    assert '<form class="remix-loader" id="remixLoader"' in html
    assert "novalidate" in html
    assert 'addEventListener("submit"' in remix
    assert "alert(" not in remix
    assert "aria-busy" in remix
    assert "loadGeneration" in remix
    assert "window.history.replaceState" in remix
    assert "window.WorkBridge.save" in remix
    gallery_line = next(line for line in remix.splitlines() if "let galleryId =" in line)
    assert 'params.get("group")' not in gallery_line


def test_character_editor_leads_with_detected_slots_and_reports_initialization_failure():
    panel = read("web/plugins/char-swap/panel.js")
    assert "角色与画风草稿" in panel
    assert "生图工作台</strong>" not in panel
    assert panel.index('class="char-swap-slots-draft"') < panel.index('id="charSwapQuickPresets"')


def test_batch_queue_isolated_by_gallery_and_sends_gallery_to_backend():
    batch = read("web/plugins/char-swap/batch.js")
    plugin = read("web/plugins/char-swap/plugin.js")
    assert "normalizeGalleryId" in batch.split("\n", 1)[0]
    assert "export function currentBatchGalleryId" in batch
    assert "gallery_id: currentBatchGalleryId" in batch
    assert "gallery_id: x.gallery_id" in batch
    assert "batchKey(x.work_id, x.page_index, x.gallery_id)" in batch
    assert 'data-gallery-id="${esc(item.gallery_id)}"' in batch
    assert "currentBatchGalleryId" in plugin
    assert "batchKey(x.work_id, x.page_index, x.gallery_id)" in plugin
