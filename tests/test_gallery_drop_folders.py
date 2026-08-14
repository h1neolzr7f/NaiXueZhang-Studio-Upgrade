from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_main_gallery_drop_dock_is_wired_for_codex_and_qqgroup() -> None:
    html = read("web/index.html")
    app = read("web/app.js")
    drop = read("web/shared/gallery-drop-folders.js")
    client = read("web/shared/api-client.js")
    plugin = read("web/plugins/char-swap/plugin.js")
    assert 'id="galleryDropDock"' in html
    assert 'id="galleryDropzone"' in html
    assert 'id="galleryFolderRail"' in html
    assert "/assets/shared/gallery-drop-folders.js" in html
    assert "GalleryDropFolders" in drop
    assert "/api/gallery/" in drop and "import-drop" in drop
    assert "/folders/merge" in drop
    assert "加入批量换角" in drop
    assert 'new Set(["codex", "qqgroup"])' in drop
    assert "loadCharSwapPlugin" in drop
    assert 'page_size: "120"' in drop
    assert "window.GalleryDropFolders.sync" in app
    assert "window.fetchWorks = fetchWorks" in app
    assert "galleryGroupSel.value = ''" in app
    assert "文件夹 ·" in app
    assert "addManyToBatch" in plugin
    assert "instanceof FormData" in client
    assert "还没有作品。把带 NovelAI 元数据的图片拖进这块区域" in read("web/app-core.js")
    assert 'id="galleryDropPickFolder"' in html
    assert "webkitGetAsEntry" in drop
    assert "galleryDropPickFolder" in drop
    assert "正在导入上一批" in drop
    assert "window.confirm" in drop
    assert "都已在批量队列中" in drop
    assert "dropGalleryId" in drop
    assert "isIgnoredDropTarget" in drop
    assert "新建并合并" in drop
    assert '"__new__"' not in drop
    assert "导入超时，请减少一次拖入的张数后重试。" in drop
    assert "group_label" not in read("routes/gallery.py").split("def _work_folder_names")[1].split("def ")[0]
    assert "setNoResultMessage(t('no_results'))" in read("web/app-core.js")
    assert "_DROP_MAX_TOTAL_BYTES" in read("routes/gallery.py")
    assert "LIMIT 20000" not in read("gallery_catalog.py")
    assert "其中 ${existing} 张已在库中，仍留在原文件夹" in drop
