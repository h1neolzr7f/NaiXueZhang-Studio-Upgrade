from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ANDROID = ROOT / "android"


class MobileStandaloneTests(unittest.TestCase):
    def test_phone_app_is_not_a_pc_remote(self) -> None:
        main = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/MainActivity.java").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("askServerUrl", main)
        self.assertNotIn("工作室地址", main)
        self.assertIn("127.0.0.1", main)
        self.assertIn("/m", main)
        self.assertIn("18797", main)
        self.assertIn("PhoneApp", main)
        self.assertIn("openAitagVerify", main)
        self.assertIn("SettingsActivity", main)
        demo = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/DemoWorks.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("demo-ark-amiya", demo)
        self.assertIn("nai-diffusion-4-5-full", demo)
        self.assertIn("waitForLocalServer", (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/SplashActivity.java").read_text(encoding="utf-8"))
        self.assertIn("onReceivedError", main)
        self.assertIn("MIXED_CONTENT_COMPATIBILITY_MODE", main)
        self.assertNotIn("192.168.", main)
        manifest = (ANDROID / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn(".StudioApp", manifest)
        self.assertIn(".SplashActivity", manifest)
        self.assertIn(".SettingsActivity", manifest)
        self.assertIn("@mipmap/ic_launcher", manifest)
        self.assertIn("Theme.NaiPhone", manifest)
        splash = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/SplashActivity.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("MainActivity", splash)
        settings = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/SettingsActivity.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("TokenStore", settings)
        self.assertIn("DeepSeek", settings)
        strings = (ANDROID / "app/src/main/res/values/strings.xml").read_text(encoding="utf-8")
        self.assertIn("NovelAI", strings)
        self.assertIn("DeepSeek", strings)
        self.assertIn("不遥控电脑", strings)
        self.assertIn("搜图 / 写角色走代理", strings)
        self.assertIn("出图走代理", strings)
        icon = ANDROID / "app/src/main/res/mipmap-xxxhdpi/ic_launcher.png"
        self.assertTrue(icon.is_file())
        note = (ANDROID / "说明.txt").read_text(encoding="utf-8")
        self.assertIn("不连电脑", note)
        self.assertIn("NovelAI Token", note)
        self.assertIn("DeepSeek", note)
        self.assertIn("不遥控", note)
        self.assertNotIn("工作室地址", note)

    def test_local_server_keeps_paid_gates(self) -> None:
        server = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/LocalStudioServer.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("force_free", server)
        self.assertIn("/api/nai/generate", server)
        self.assertIn("/api/nai/token", server)
        self.assertIn("/api/ai/key", server)
        self.assertIn("/api/studio/optimize", server)
        self.assertIn("/api/mobile/char-describe", server)
        self.assertIn("手机独立版不读取电脑待生成队列", server)
        generator = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/NaiGenerator.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("image.novelai.net", generator)
        self.assertIn("http_5xx", generator)
        self.assertIn("routeNai", generator)
        self.assertNotIn("System.out.println(token", generator)
        outbound = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/HttpOutbound.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("Proxy.NO_PROXY", outbound)
        self.assertIn("resolveSafeRedirect", outbound)
        tokens = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/TokenStore.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("online_use_proxy", tokens)
        self.assertIn("nai_use_proxy", tokens)
        self.assertIn("127.0.0.1", tokens)
        self.assertIn("detectLocalProxy", tokens)
        self.assertIn("onlineCandidates", tokens)
        self.assertIn("parseTokens", tokens)
        self.assertIn("lease(", tokens)
        self.assertIn("release(", tokens)
        self.assertIn("token_count", tokens)
        self.assertIn("concurrency", tokens)
        gateway = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/AitagGateway.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("image_count", gateway)
        self.assertIn("onlineCandidates", gateway)
        self.assertIn("BrowserSession", gateway)
        self.assertIn("unwrapAiJson", gateway)
        self.assertIn("offline_demo", gateway)
        self.assertIn("DemoWorks", gateway)
        browser = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/BrowserSession.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("aitag.win", browser)
        self.assertIn("showVerify", browser)
        self.assertIn("NaiPipe", browser)

    def test_web_shell_has_standalone_mode(self) -> None:
        js = (WEB / "m" / "m.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bfetch\s*\(", js))
        self.assertIn("isStandalone", js)
        self.assertIn("StandaloneCore", js)
        self.assertIn("force_free: true", js)
        self.assertIn("generation_calls", js)
        self.assertIn("先在设置里填 NovelAI Token", js)
        self.assertIn("手机本地", js)
        self.assertIn("openSettings", js)
        self.assertIn("PhoneApp", js)
        self.assertIn("搜明日方舟", js)
        self.assertIn("保存自定义", js)
        self.assertIn("点开搜索", js)
        self.assertIn("收藏", js)
        self.assertIn("本地库", js)
        self.assertIn("image_count", js)
        self.assertIn("/api/nai/aitag/favorites", js)
        self.assertIn("/api/mobile/library/work/", js)
        self.assertIn("/api/plugin/char-swap/search", js)
        self.assertIn("张", js)
        self.assertIn("candidate_id", js)
        self.assertIn("manageBusy", js)
        self.assertIn("开始在线批量", js)
        self.assertIn("DeepSeek 写角色", js)
        self.assertIn("/api/mobile/char-describe", js)
        self.assertIn("不遥控电脑", js)
        self.assertIn("三步就会用", js)
        self.assertIn("standalone=1", js)
        self.assertIn("friendlyError", js)
        self.assertIn("在线库暂时打不开", js)
        self.assertIn("测试在线库", js)
        self.assertIn("打开在线库过验证", js)
        self.assertIn("/api/nai/aitag/probe", js)
        self.assertIn("openAitagVerify", js)
        self.assertIn("草稿预览", js)
        self.assertIn("下一页", js)
        self.assertIn("内置样例", js)
        self.assertIn("demo-ark-amiya", js)
        self.assertIn("先收藏入本地库", js)
        self.assertIn("入库还没完成", js)
        self.assertIn("手改草稿", js)
        self.assertIn("applyDraftEdits", js)
        self.assertIn("删除这组", js)
        self.assertIn("/cancel", js)
        self.assertIn("/retry", js)
        self.assertIn("每行一个", js)
        self.assertIn("正在搜", js)
        self.assertIn("debounce", js)
        self.assertIn("concurrency", js)
        self.assertIn("路并发", js)
        self.assertIn("browseSearchSeq", js)
        self.assertIn("mBrowsePager", js)
        self.assertIn("D 站角色库", js)
        self.assertIn("画风", js)
        self.assertIn("/api/mobile/gallery", js)
        self.assertIn("/api/mobile/queue", js)
        self.assertIn("/api/plugin/char-swap/styles", js)
        self.assertGreaterEqual(js.count("先在设置里填 NovelAI Token"), 2)
        css = (WEB / "m" / "m.css").read_text(encoding="utf-8")
        self.assertIn("min-height: 44px", css)
        self.assertIn("--kb", css)
        core = (WEB / "m" / "standalone-core.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bfetch\s*\(", core))
        self.assertIn("generation_calls: 0", core)
        self.assertIn("buildGeneratePayload", core)
        self.assertIn("applyOptimizeTexts", core)
        self.assertIn("applyDraftEdits", core)
        self.assertIn("analyzeSlotCaption", core)
        self.assertIn("imageComment", core)
        self.assertIn("promptSnapshot", core)
        self.assertIn("没找到这个角色槽", core)
        server = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/LocalStudioServer.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("/api/plugin/char-swap/custom", server)
        self.assertIn("CustomCharStore", server)
        self.assertIn("FavoriteStore", server)
        self.assertIn("/api/nai/aitag/favorites", server)
        self.assertIn("/api/mobile/library", server)
        self.assertIn("/api/plugin/char-swap/search", server)
        self.assertIn("/api/nai/network", server)
        self.assertIn("/api/nai/aitag/probe", server)
        self.assertIn("/api/mobile/gallery", server)
        self.assertIn("/api/mobile/queue", server)
        self.assertIn("/cancel", server)
        self.assertIn("/retry", server)
        self.assertIn("/delete", server)
        self.assertIn("StyleStore", server)
        self.assertIn("GalleryStore", server)
        self.assertIn("先收藏入本地库", server)
        self.assertIn("入库还没完成", server)
        self.assertIn("token_count", server)
        self.assertIn("concurrency", server)
        self.assertIn("phone-char-index", server)
        self.assertIn("warmup", server)
        jobs = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/JobStore.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("newFixedThreadPool(8)", jobs)
        self.assertIn("路并发", jobs)
        self.assertIn("CountDownLatch", jobs)
        chars = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/CharLibrary.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("phone_char_index.txt", chars)
        self.assertIn("char_tag_index.json", chars)
        self.assertIn("phone_copyright_index.txt", chars)
        self.assertIn("D 站角色库", chars)
        self.assertIn("phone_series_aliases.json", chars)
        self.assertIn("prefixIndex", chars)
        self.assertIn("resolveAlias", chars)
        self.assertIn("searchCache", chars)
        index = ROOT / "data" / "phone_char_index.txt"
        self.assertTrue(index.is_file())
        self.assertGreaterEqual(index.read_text(encoding="utf-8").count("\n"), 300000)
        gradle = (ANDROID / "app/build.gradle").read_text(encoding="utf-8")
        self.assertIn("char_tag_index.json", gradle)
        self.assertIn("tag_dict.json", gradle)
        pipeline = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/PipelineStore.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("PhonePipeline.process", pipeline)
        self.assertIn("upscale", pipeline)
        self.assertIn("metadata", pipeline)
        phonePipe = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/PhonePipeline.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("FILTER_BITMAP_FLAG", phonePipe)
        self.assertIn("PNG", phonePipe)

    def test_phone_preview_search_ranks_popular_names(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "phone_preview_server",
            ROOT / "scripts" / "phone_preview_server.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.assertGreaterEqual(len(module.CHAR_INDEX), 300000)
        ganyu = module._search_chars("female", "甘雨", 8)
        tags = [str((item.get("record") or {}).get("tag") or "") for item in ganyu]
        self.assertTrue(any(tag.startswith("ganyu") for tag in tags), tags[:6])
        miku = module._search_chars("female", "初音", 8)
        tags = [str((item.get("record") or {}).get("tag") or "") for item in miku]
        self.assertTrue(any("hatsune" in tag for tag in tags), tags[:6])
        tokens = module._parse_tokens("aaa\nBearer bbb\n# skip\naaa,ccc")
        self.assertEqual(tokens, ["aaa", "bbb", "ccc"])
        preview = (ROOT / "scripts" / "phone_preview_server.py").read_text(encoding="utf-8")
        self.assertIn("token_count", preview)
        self.assertIn("concurrency", preview)
        self.assertIn("_ensure_char_indexes", preview)

    def test_user_guide_describes_phone_local_app(self) -> None:
        guide = (ROOT / "使用说明.txt").read_text(encoding="utf-8")
        self.assertIn("安卓独立应用", guide)
        self.assertIn("不需要先开电脑工作室", guide)
        self.assertIn("小白三步", guide)
        self.assertNotIn("输入 6 位配对码后，即可在线换角", guide)

    def test_standalone_core_node_contract(self) -> None:
        script = ROOT / "tests" / "standalone_core_test.js"
        completed = subprocess.run(
            ["node", str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("standalone-core ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()
