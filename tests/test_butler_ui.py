from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ButlerUiTests(unittest.TestCase):
    def test_butler_page_uses_shared_navigation_and_api_client(self) -> None:
        html = (ROOT / "web" / "butler.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "butler.js").read_text(encoding="utf-8")
        self.assertIn('/assets/shared/site-nav.js', html)
        self.assertIn('/assets/shared/api-client.js', html)
        self.assertIn('/assets/butler.js', html)
        self.assertIn("window.ApiClient", js)
        self.assertIsNone(re.search(r"\bfetch\s*\(", js))

    def test_gallery_detail_loads_char_swap_only_after_detail_ready(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        hooks = (ROOT / "web" / "shared" / "gallery-detail-hooks.js").read_text(encoding="utf-8")
        self.assertIn("/assets/shared/gallery-detail-hooks.js", html)
        self.assertIn('window.addEventListener("aitag:detail-ready"', hooks)
        self.assertIn("await loadCharSwapPlugin()", hooks)
        self.assertIn("await plugin.mountDetail(workId, data)", hooks)
        self.assertIn("loadCharSwapStyles()", hooks)
        self.assertIn("char-swap.css", hooks)
        self.assertNotIn('/assets/plugins/char-swap/plugin.js', html)
        self.assertNotIn('char-swap.css', html)

    def test_ui_has_confirmation_workflow_and_studio_handoff(self) -> None:
        html = (ROOT / "web" / "butler.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "butler.js").read_text(encoding="utf-8")
        self.assertIn("/api/butler/confirm", js)
        self.assertIn("confirmation_id", js)
        self.assertIn("aitag.studio.draft.v1", js)
        self.assertIn("ready_for_upload", js)
        self.assertIn("前往投稿台检查并上传", js)
        self.assertIn('tool === "prepare_remix"', js)
        self.assertIn('isStyle ? "换画风" : "换角"', js)
        self.assertIn("预检：${subject}", js)
        self.assertIn("task.pending_action", js)
        self.assertIn("换角核验", js)
        self.assertIn("换画风核验", js)
        self.assertIn("换画风草稿已准备", js)
        self.assertIn("换画风生成", html)
        self.assertIn("管理收藏", html)
        self.assertIn("补跑后处理", html)
        self.assertIn('tool === "list_favorites"', js)
        self.assertIn('tool === "list_generated"', js)
        self.assertIn('tool === "inspect_crawler"', js)
        self.assertIn('tool === "inspect_capabilities"', js)

    def test_task_center_supports_detail_cancel_retry_resume_and_timeline(self) -> None:
        html = (ROOT / "web" / "butler.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "butler.js").read_text(encoding="utf-8")
        for marker in ("taskList", "taskDetail", "refreshTasks"):
            self.assertIn(marker, html)
        self.assertIn('"/api/butler/tasks?limit=20"', js)
        self.assertIn('/${action}`', js)
        for action in ('"cancel"', '"retry"', '"resume"'):
            self.assertIn(action, js)
        self.assertIn("执行时间线", js)
        for marker in ("预计进行步骤", "接下来", "打开交付报告", "交付结果", "需要留意"):
            self.assertIn(marker, js)
        self.assertIn("butler-delivery-report", js)
        self.assertIn("butler-step-list", js)
        self.assertIn('id="taskCenter"', html)
        self.assertIn("new URLSearchParams(window.location.search)", js)
        self.assertIn('.get("task")', js)

    def test_companion_feedback_distinguishes_handoff_progress_and_delivery(self) -> None:
        js = (ROOT / "web" / "butler.js").read_text(encoding="utf-8")
        for marker in (
            "任务接住啦，我会盯着每一步",
            "正在替你做",
            "交付报告也替你整理好了",
            "顺利完成啦，报告已经整理好",
        ):
            self.assertIn(marker, js)
        self.assertNotIn('setMood("happy", "完成啦，能帮上你真好")', js)

    def test_companion_uses_durable_history_local_live2d_and_adaptive_polling(self) -> None:
        html = (ROOT / "web" / "butler.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "butler.js").read_text(encoding="utf-8")
        for marker in ("data-assistant-name", "loadOlderHistory", "assistantMood"):
            self.assertIn(marker, html)
        for marker in (
            '"/api/butler/history',
            '"/api/settings/prefs"',
            'L2D_WIDGET.createWidget',
            '"/assets/vendor/l2d-widget/index.min.js?v=',
            "visibilitychange",
            "document.hidden",
            "window.setTimeout",
            "menus: { items: [] }",
        ):
            self.assertIn(marker, js)
        self.assertNotIn("sessionStorage", js)
        self.assertNotIn("window.setInterval(", js)
        self.assertIn("selected_id=", js)
        self.assertIn("selected_task", js)
        self.assertIn("activatePollBurst", js)
        self.assertIn("const statusPromise = loadStatus()", js)
        self.assertNotIn("await loadStatus({ skipTasks: true })", js)
        self.assertIn('new EventSource("/api/butler/tasks/stream', js)
        self.assertIn("startTaskStream", js)
        self.assertIn("taskStreamConnected", js)
        self.assertIn("schedulePoll", js)
        self.assertIn("redactSensitiveText", js)
        self.assertIn("content: safeContent", js)

    def test_live2d_is_mounted_in_a_dedicated_stage_and_chat_accepts_images(self) -> None:
        html = (ROOT / "web" / "butler.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "butler.css").read_text(encoding="utf-8")
        js = (ROOT / "web" / "butler.js").read_text(encoding="utf-8")

        for marker in (
            'id="live2dStage"',
            'id="imageInput"',
            'id="imagePreview"',
            'id="stageAuditGallery"',
            'accept="image/png,image/jpeg,image/webp"',
            'href="/settings#ai-service"',
        ):
            self.assertIn(marker, html)
        self.assertIn("aspect-ratio: 3 / 4", css)
        self.assertIn("transform: scale(1.85)", css)
        self.assertIn("bindLive2dTouch", js)
        self.assertIn("/assets/shared/live2d-touch.js", html)
        self.assertIn("playCompanionMotion", js)
        self.assertIn("compressImage", js)
        self.assertIn("pendingImage", js)
        self.assertIn("image: attachment", js)
        self.assertIn('intent: "gallery_audit"', js)
        self.assertIn('tool === "audit_gallery"', js)
        self.assertIn("butler-audit-persisted", js)
        self.assertIn("agent: state.agent", js)
        self.assertIn('get("agent")', js)
        self.assertIn("switchModel", js)
        self.assertIn("playMotion", js)
        self.assertIn("pickCostumeId", js)
        self.assertIn("companions.json", js)
        self.assertIn('id="agentSwitch"', html)
        self.assertIn("助手凑企鹅", html)

    def test_live2d_catalog_keeps_all_sakiko_and_tomori_costumes(self) -> None:
        catalog = json.loads((ROOT / "web" / "vendor" / "live2d-models" / "companions.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["tomori"]["name"], "助手凑企鹅")
        sakiko = catalog["sakiko"]["costumes"]
        tomori = catalog["tomori"]["costumes"]
        self.assertGreaterEqual(len(sakiko), 4)
        self.assertGreaterEqual(len(tomori), 8)
        self.assertIn("causal", sakiko)
        self.assertIn("school_summer", sakiko)
        self.assertIn("jh_school_winter", sakiko)
        self.assertIn("casual", tomori)
        self.assertIn("live_default", tomori)
        self.assertIn("furisode", tomori)
        self.assertGreaterEqual(catalog["sakiko"]["scale"], 1.0)
        self.assertGreaterEqual(catalog["tomori"]["scale"], 1.0)
        self.assertNotEqual(catalog["sakiko"]["situations"]["ready"], "school_winter")
        self.assertNotEqual(catalog["tomori"]["situations"]["generate"], "school_winter")
        for costume in list(sakiko.values()) + list(tomori.values()):
            model = ROOT / costume["path"].replace("/assets/", "web/", 1).lstrip("/")
            self.assertTrue(model.is_file(), model)
            payload = json.loads(model.read_text(encoding="utf-8"))
            for group in ("idle", "tap_body", "happy", "thinking", "sorry"):
                self.assertIn(group, payload["motions"])
            self.assertGreaterEqual(len(payload["motions"]), 40)

    def test_fixed_candidate_compare_workspace_is_explicit_and_persistent(self) -> None:
        html = (ROOT / "web" / "butler.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "butler.css").read_text(encoding="utf-8")
        js = (ROOT / "web" / "butler.js").read_text(encoding="utf-8")

        for marker in (
            'id="butlerCompareWorkspace"',
            'id="butlerCompareGrid"',
            'id="runGalleryCompare"',
            "会调用识图",
        ):
            self.assertIn(marker, html)
        self.assertIn("COMPARISON_KEY", js)
        self.assertIn("addComparisonCandidate", js)
        self.assertIn('intent: "gallery_compare"', js)
        self.assertIn("comparison: comparisonCandidates", js)
        self.assertIn('tool === "compare_gallery_candidates"', js)
        self.assertIn("grid-template-columns: repeat(2", css)

    def test_saved_task_templates_only_fill_the_composer(self) -> None:
        html = (ROOT / "web" / "butler.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "butler.js").read_text(encoding="utf-8")
        for marker in ('id="butlerTemplates"', 'id="saveTemplateBtn"'):
            self.assertIn(marker, html)
        self.assertIn('"/api/butler/templates"', js)
        self.assertIn("renderTemplates", js)
        self.assertIn("fillTemplate", js)

    def test_butler_keeps_desktop_layout_and_adds_mobile_stacking(self) -> None:
        css = (ROOT / "web" / "butler.css").read_text(encoding="utf-8")
        self.assertIn("min-width: 1180px", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("scrollbar-width: thin", css)
        self.assertIn("transform-origin: 50% 8%", css)
        self.assertIn("@media (max-width: 900px)", css)
        self.assertIn(".butler-body {\n    min-width: 0;", css)
        self.assertIn(".butler-layout {\n    grid-template-columns: minmax(0, 1fr);", css)

    def test_pixiv_page_can_load_prepared_package_without_auto_upload(self) -> None:
        js = (ROOT / "web" / "pixiv.js").read_text(encoding="utf-8")
        self.assertIn("/api/pixiv/prepared", js)
        self.assertIn("preparedUploadPayload", js)
        self.assertIn("applyPreparedPackage", js)
        self.assertIn("package_id=${encodeURIComponent(packageId)}", js)
        self.assertIn("selectPreparedDraft", js)
        self.assertIn("prepared.items", js)
        self.assertIn("只会上传当前草稿", js)
        self.assertNotIn('applyPreparedPackage().then(() => doLaunch', js)


if __name__ == "__main__":
    unittest.main()
