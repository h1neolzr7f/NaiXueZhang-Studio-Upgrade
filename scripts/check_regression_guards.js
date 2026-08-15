#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");
const failures = [];

function expect(name, ok, hint) {
  if (!ok) failures.push(`${name}: ${hint}`);
}

function includesAll(name, text, snippets) {
  for (const snippet of snippets) {
    expect(name, text.includes(snippet), `missing ${JSON.stringify(snippet)}`);
  }
}

const indexHtml = read("web/index.html");
const appCoreJs = read("web/app-core.js");
// app.js 已按域拆分：详情/悬停预览在 app-detail.js，线上换角在 app-online-remix.js
const appJs = [
  "web/app.js",
  "web/app-detail.js",
  "web/app-online-remix.js",
].map(read).join("\n");
const generatedHtml = read("web/generated.html");
const charSwapPanel = read("web/plugins/char-swap/panel.js");
const charSwapPlugin = read("web/plugins/char-swap/plugin.js");

// Cache-bust stamps are content-hashed and machine-maintained:
// `python3 scripts/asset_versions.py --check` fails when any ?v= drifted.
{
  const spawn = require("child_process").spawnSync;
  const args = ["scripts/asset_versions.py", "--check"];
  const candidates = process.platform === "win32"
    ? ["python", "py", "python3"]
    : ["python3", "python"];
  let res;
  for (const cmd of candidates) {
    res = spawn(cmd, args, { cwd: root, encoding: "utf8" });
    if (res.error && res.error.code === "ENOENT") continue;
    break;
  }
  expect(
    "asset cache-bust stamps match content hashes",
    Boolean(res) && res.status === 0,
    `stale ?v= stamps; run python3 scripts/asset_versions.py\n${(res && res.stdout) || ""}${(res && res.stderr) || ""}`,
  );
}

includesAll("generated gallery prompt fallback", generatedHtml, [
  "function sourcePromptToSnapshot(sourcePrompt)",
  "function appendItemPrompt(box, item, sourcePrompt)",
  "const snap = ownSnap || sourcePromptToSnapshot(sourcePrompt);",
  "function renderDetailItem(item, groupId, sourcePrompt)",
  "appendItemPrompt(box, item, sourcePrompt);",
  "data.source_prompt || null",
]);

includesAll("favorites should not block entry on eager thumbnails", appJs, [
  "img.loading = state.favoritesMode ? 'lazy'",
  "img.fetchPriority = state.favoritesMode ? 'low' : 'high'",
  "loadCachedFavorites();",
  "if (!state.favoritesMode) loadFavorites().catch(() => {});",
  "const configPromise = loadConfig().catch(() => {});",
]);

includesAll("char-swap dynamic plugin cache bust", read("web/shared/gallery-detail-hooks.js"), [
  'const PLUGIN_URL = "/assets/plugins/char-swap/plugin.js?v=',
]);

includesAll("gallery performance modules wired", indexHtml, [
  "/assets/shared/gallery-virtual.js",
  "/assets/shared/prompt-preview.js",
  "/assets/shared/gallery-bootstrap.js",
]);

includesAll("hover preview uses lite work api", appJs, [
  "fetchWorkLite",
  "/api/work/${workId}/lite",
  "GalleryVirtual.observeCard",
]);

includesAll("char-swap detail current guard", charSwapPlugin, [
  "const cached = currentDetailPayload();",
  "if (!cached || normalizeWorkId(cached.workId) !== normalizeWorkId(workId)) return;",
  'if (document.getElementById("charSwapPanel")) return;',
]);

expect(
  "char-swap plugin must not be a synchronous index script",
  !/script[^>]+plugins\/char-swap\/plugin\.js/.test(indexHtml),
  "web/index.html must not synchronously load the char-swap plugin on gallery entry pages",
);
expect(
  "gallery entry must not auto-import char-swap plugin",
  !appJs.includes("scheduleCharSwapPluginIdleLoad"),
  "web/app.js must not auto-import char-swap on gallery entry pages",
);

includesAll("token pool ui is configurable and checkable", charSwapPanel, [
  'id="charSwapToken"',
  "NAI / Xianyun Token Pool",
  "pst-xxx (NovelAI)",
  "xianyun:API_KEY",
  'id="charSwapAddToken"',
  'id="charSwapCheckTokens"',
  'id="charSwapTokenSlots"',
  "/api/nai/token/add",
  "/api/nai/token/check",
]);

if (failures.length) {
  console.error(JSON.stringify({ ok: false, failures }, null, 2));
  process.exit(1);
}

console.log(JSON.stringify({
  ok: true,
  checks: [
    "asset cache-bust stamps match content hashes (scripts/asset_versions.py --check)",
    "generated gallery prompt fallback wiring",
    "favorites lazy/low priority thumbnails + no redundant favorites summary on favorites page",
    "char-swap plugin is delayed off gallery entry",
    "token pool UI + token check endpoints",
  ],
}, null, 2));
