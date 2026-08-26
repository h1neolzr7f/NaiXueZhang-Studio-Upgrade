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
        self.assertIn("SettingsActivity", main)
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
        self.assertNotIn("System.out.println(token", generator)

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
        self.assertIn("candidate_id", js)
        self.assertIn("manageBusy", js)
        self.assertIn("开始在线批量", js)
        self.assertIn("DeepSeek 写角色", js)
        self.assertIn("/api/mobile/char-describe", js)
        self.assertIn("不遥控电脑", js)
        self.assertGreaterEqual(js.count("先在设置里填 NovelAI Token"), 2)
        core = (WEB / "m" / "standalone-core.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bfetch\s*\(", core))
        self.assertIn("generation_calls: 0", core)
        self.assertIn("buildGeneratePayload", core)
        self.assertIn("applyOptimizeTexts", core)
        self.assertIn("analyzeSlotCaption", core)
        self.assertIn("没找到这个角色槽", core)
        server = (ANDROID / "app/src/main/java/com/naixuezhang/studio/mobile/LocalStudioServer.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("/api/plugin/char-swap/custom", server)
        self.assertIn("CustomCharStore", server)

    def test_user_guide_describes_phone_local_app(self) -> None:
        guide = (ROOT / "使用说明.txt").read_text(encoding="utf-8")
        self.assertIn("安卓独立应用", guide)
        self.assertIn("不需要先开电脑工作室", guide)
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
