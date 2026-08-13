from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendApiClientTests(unittest.TestCase):
    def test_api_client_exists_and_exposes_methods(self) -> None:
        src = (ROOT / "web" / "shared" / "api-client.js").read_text(encoding="utf-8")
        self.assertIn("window.ApiClient", src)
        self.assertIn("request", src)
        self.assertIn("get", src)
        self.assertIn("post", src)
        self.assertIn("raw", src)
        self.assertIn("AbortController", src)

    def test_raw_api_client_preserves_response_contract(self) -> None:
        client_path = ROOT / "web" / "shared" / "api-client.js"
        script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const calls = [];
const response = { ok: true, status: 204, json: async () => ({ ok: true }) };
const context = {
  window: {},
  AbortController,
  setTimeout,
  clearTimeout,
  fetch: async (path, init) => {
    if (path === "/api/session-token") return { ok: true, json: async () => ({ token: "t" }) };
    calls.push({ path, init });
    return response;
  },
};
vm.runInNewContext(source, context);
context.window.ApiClient.raw('/api/example', { method: 'POST', body: '{"x":1}' })
  .then((result) => process.stdout.write(JSON.stringify({
    sameResponse: result === response,
    path: calls[0].path,
    method: calls[0].init.method,
    body: calls[0].init.body,
  })))
  .catch((error) => { console.error(error); process.exit(1); });
"""
        result = subprocess.run(
            ["node", "-e", script, str(client_path)],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(
            result.stdout,
            '{"sameResponse":true,"path":"/api/example","method":"POST","body":"{\\"x\\":1}"}',
        )

    def test_session_token_failure_is_not_cached_and_retry_succeeds(self) -> None:
        client_path = ROOT / "web" / "shared" / "api-client.js"
        script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
let sessionHits = 0;
const posts = [];
const context = {
  window: {},
  AbortController,
  setTimeout,
  clearTimeout,
  fetch: async (path, init) => {
    if (path === "/api/session-token") {
      sessionHits += 1;
      if (sessionHits === 1) return { ok: false, status: 503, json: async () => ({}) };
      return { ok: true, json: async () => ({ token: "tok-ok" }) };
    }
    posts.push({ path, header: (init.headers || {})["X-Session-Token"] });
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  },
};
vm.runInNewContext(source, context);
(async () => {
  try {
    await context.window.ApiClient.raw('/api/example', { method: 'POST', body: '{}' });
    process.stdout.write('unexpected-success');
    process.exit(2);
  } catch (_) {}
  await context.window.ApiClient.raw('/api/example', { method: 'POST', body: '{}' });
  process.stdout.write(JSON.stringify({ sessionHits, header: posts[0] && posts[0].header, posts: posts.length }));
})().catch((error) => { console.error(error); process.exit(1); });
"""
        result = subprocess.run(
            ["node", "-e", script, str(client_path)],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stdout, '{"sessionHits":2,"header":"tok-ok","posts":1}')

    def test_write_401_clears_session_and_retries_once(self) -> None:
        client_path = ROOT / "web" / "shared" / "api-client.js"
        script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
let sessionHits = 0;
const posts = [];
const context = {
  window: {},
  AbortController,
  setTimeout,
  clearTimeout,
  fetch: async (path, init) => {
    if (path === "/api/session-token") {
      sessionHits += 1;
      return { ok: true, json: async () => ({ token: sessionHits === 1 ? "old" : "new" }) };
    }
    posts.push((init.headers || {})["X-Session-Token"]);
    if (posts.length === 1) return { ok: false, status: 401, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  },
};
vm.runInNewContext(source, context);
context.window.ApiClient.raw('/api/example', { method: 'POST', body: '{}' })
  .then(() => process.stdout.write(JSON.stringify({ sessionHits, posts })))
  .catch((error) => { console.error(error); process.exit(1); });
"""
        result = subprocess.run(
            ["node", "-e", script, str(client_path)],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stdout, '{"sessionHits":2,"posts":["old","new"]}')

    def test_ops_uses_shared_api_client(self) -> None:
        html = (ROOT / "web" / "ops.html").read_text(encoding="utf-8")
        self.assertIn('/assets/shared/api-client.js', html)
        self.assertIn("window.ApiClient.get", html)
        self.assertNotIn("fetch(\"/api/product", html)

    def test_settings_uses_shared_api_client(self) -> None:
        html = (ROOT / "web" / "settings.html").read_text(encoding="utf-8")
        src = (ROOT / "web" / "settings.js").read_text(encoding="utf-8")
        self.assertIn('/assets/shared/api-client.js', html)
        self.assertIn("window.ApiClient.request", src)
        self.assertNotIn("await fetch(", src)

    def test_studio_uses_shared_api_client(self) -> None:
        html = (ROOT / "web" / "studio.html").read_text(encoding="utf-8")
        src = (ROOT / "web" / "studio.js").read_text(encoding="utf-8")
        self.assertIn('/assets/shared/api-client.js', html)
        self.assertIn("window.ApiClient.request", src)
        self.assertNotIn("await fetch(", src)

    def test_new_asset_and_pipeline_pages_use_shared_api_client(self) -> None:
        for name in ["tag-assets", "pipeline"]:
            with self.subTest(name=name):
                html = (ROOT / "web" / f"{name}.html").read_text(encoding="utf-8")
                src = (ROOT / "web" / f"{name}.js").read_text(encoding="utf-8")
                self.assertIn('/assets/shared/api-client.js', html)
                self.assertIn("window.ApiClient", src)

    def test_generated_uses_shared_api_client(self) -> None:
        html = (ROOT / "web" / "generated.html").read_text(encoding="utf-8")
        self.assertIn('/assets/shared/api-client.js', html)
        self.assertIn("window.ApiClient", html)
        self.assertNotIn("fetch(", html)

    def test_pixiv_workbench_is_externalized(self) -> None:
        html_path = ROOT / "web" / "pixiv.html"
        html = html_path.read_text(encoding="utf-8")
        css = ROOT / "web" / "pixiv.css"
        js = ROOT / "web" / "pixiv.js"

        self.assertTrue(css.exists())
        self.assertTrue(js.exists())
        self.assertIn('/assets/pixiv.css', html)
        self.assertIn('/assets/pixiv.js', html)
        self.assertNotIn("<style>", html)
        self.assertNotIn("<script>", html)
        self.assertLessEqual(len(html.splitlines()), 1500)

    def test_gallery_and_pixiv_use_shared_client_for_same_origin_requests(self) -> None:
        pages = {
            "index": (ROOT / "web" / "index.html").read_text(encoding="utf-8"),
            "pixiv": (ROOT / "web" / "pixiv.html").read_text(encoding="utf-8"),
        }
        scripts = {
            "app": (ROOT / "web" / "app.js").read_text(encoding="utf-8"),
            "app-core": (ROOT / "web" / "app-core.js").read_text(encoding="utf-8"),
            "pixiv": (ROOT / "web" / "pixiv.js").read_text(encoding="utf-8"),
        }

        for page_name, html in pages.items():
            with self.subTest(page=page_name):
                self.assertIn('/assets/shared/api-client.js', html)
        self.assertLess(
            pages["index"].index('/assets/shared/api-client.js'),
            pages["index"].index('/assets/app-core.js'),
        )
        self.assertLess(
            pages["pixiv"].index('/assets/shared/api-client.js'),
            pages["pixiv"].index('/assets/pixiv.js'),
        )
        for script_name, src in scripts.items():
            with self.subTest(script=script_name):
                self.assertIn("window.ApiClient.raw", src)
                self.assertIsNone(
                    re.search(r"\bfetch\s*\(", src),
                    f"{script_name} still bypasses the shared same-origin API client",
                )

    def test_gallery_frontend_core_is_split_before_app_entry(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        core = ROOT / "web" / "app-core.js"
        app = ROOT / "web" / "app.js"

        self.assertTrue(core.exists())
        self.assertIn('/assets/app-core.js', html)
        self.assertIn('/assets/app.js', html)
        self.assertLess(html.index('/assets/app-core.js'), html.index('/assets/app.js'))
        # Detail/history/remix path still lives in app.js after core split.
        # Keep a hard cap so the entry file cannot silently re-absorb app-core.
        self.assertLessEqual(len(app.read_text(encoding="utf-8").splitlines()), 4200)


if __name__ == "__main__":
    unittest.main()
