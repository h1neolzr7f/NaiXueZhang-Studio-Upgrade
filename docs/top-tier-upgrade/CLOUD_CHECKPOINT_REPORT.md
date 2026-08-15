# Nai学长工作室 · 云端检查点报告（Wave 4）

**给 dick / 后续 AI / Lead / Reviewer 的完整交接。先读本文件，再改代码。不要凭聊天记录单独开工。**

- 日期：2026-08-15
- 执行模式：`CLOUD_WEB`
- 结论：**这是云端阶段检查点，不是整个升级完成证明，也不是顶尖完成。上一版报告也不是完成证明。**
- 不要合 `main`。不要发 Release。不要用真实 NAI Token。不要连接 Manga。不要重做 Phase 0。
- Windows `WIN-001`…`015`、真实 NAI Token、真实大图库：**仍未验证。**

---

## 0. 一句话

云端能做、且本检查点要求做的四件事已经落地：

1. Studio img2img / inpaint **画布 UI**（`/app` + 经典 `/studio`）
2. 图库 incremental / similar / duplicate 的 **additive HTTP**
3. **正式审查 v1.6 / v1.7**；通过后才把 Tool Kernel **安全接入聊天**（不写 `planning.py`）
4. **v1.9**：主动事件、已确认记忆、人格交接、防打扰

TTS **不是**强制核心能力，**没有**和记忆合成一个木桶评分项。v1.9 **没有永久取消**。屏幕监听、键鼠钩子、God Agent 仍然禁止。

Windows `WIN-001`…`015` 继续留给本地接管。

---

## 1. 身份与指针

| 项 | 值 |
|---|---|
| 唯一实施仓 | `h1neolzr7f/NaiXueZhang-Studio-Upgrade` |
| 集成分支 | `cursor/cloud-top-tier-integration-f036` |
| 本报告写入提交 | `2abe9ad`（以远程 tip 为准） |
| 以远程 tip 为准 | `git rev-parse origin/cursor/cloud-top-tier-integration-f036` |
| `main` 基线（未改） | `008de38ad4dc6c8afbf0ec32ae411cd85685ac02` |
| 集成 Draft PR | https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/3 |
| Lead run | https://cursor.com/agents/bc-6ecf51c6-e504-4cfe-85d6-9b8feaf5f036 |
| Cloud Build | [bld-20260815-c10799be-3d0d-41bd-8535-6eaedb553274](https://cursor.com/dashboard/cloud-agents/builds/bld-20260815-c10799be-3d0d-41bd-8535-6eaedb553274) READY |
| 环境 | [d93c0dbf-9877-11f1-ba66-0e7d0216e441](https://cursor.com/dashboard/cloud-agents/environments/e/d93c0dbf-9877-11f1-ba66-0e7d0216e441) 个人过渡 draft，无 NAI secret |
| 请求模型 | Grok 4.6 xhigh Fast |
| 实际模型 | `cursor-grok-4.6-high-fast`（xhigh 不可单独选，已记录） |

`Manga-Editor-Desu-NAI` 与 `NaiXueZhang-Studio-Phone` 均为 `OUT_OF_SCOPE`。冻结 v1.4 仓 `NaiXueZhang-Studio` 不是升级主干（D-001 / D-008）。

历史：`CLOUD_COMPLETE_REPORT.md` 是上一波（v1.6 compile / v1.7 库级索引 / v1.8 kernel）的交接，后半节过期。**以本文件和分支 tip 为准。**

---

## 2. 先读这些文件（按顺序）

1. `docs/top-tier-upgrade/CLOUD_CHECKPOINT_REPORT.md`（本文件）
2. `docs/top-tier-upgrade/GATE_REVIEW.md`
3. `docs/top-tier-upgrade/RUN_STATE.json`
4. `docs/top-tier-upgrade/STATUS.md`
5. `docs/top-tier-upgrade/OWNERSHIP.md`
6. `docs/top-tier-upgrade/DECISIONS.md`
7. `docs/top-tier-upgrade/CAPABILITY_MATRIX.md`
8. `docs/top-tier-upgrade/NAI_PARAM_MATRIX.md`
9. `docs/top-tier-upgrade/GALLERY_INDEX_DESIGN.md`
10. `docs/top-tier-upgrade/CLOUD_PRS.md`
11. `docs/top-tier-upgrade/PENDING_LOCAL_WINDOWS.md`
12. `docs/top-tier-upgrade/HANDOFF_CLOUD_TO_WINDOWS.md`
13. `docs/top-tier-upgrade/NEXT_ACTION.md`
14. `AGENTS.md`

checkout：

```bash
git fetch origin cursor/cloud-top-tier-integration-f036
git checkout cursor/cloud-top-tier-integration-f036
git rev-parse HEAD
# 以远程 tip 为准；本轮含云端阻断项修复
```

不要从 `main` 另起炉灶。不要重做 Phase 0。

---

## 3. 硬边界

| 项 | 状态 |
|---|---|
| 唯一实施仓 | `h1neolzr7f/NaiXueZhang-Studio-Upgrade` |
| `Manga-Editor-Desu-NAI` | 禁止连接、审计、修改 |
| `NaiXueZhang-Studio-Phone` | 禁止连接 |
| 冻结 v1.4 `NaiXueZhang-Studio` | 不要当升级主干 |
| 合 `main` / Release / 改 LICENSE | 禁止 |
| Token 写入 Git / Build / 环境文件 | 禁止 |
| 无限额付费出图 | 禁止 |
| 第二套 NovelAI HTTP 客户端 | 禁止 |
| 第二套任务库 | 禁止 |
| 聊天 Tool Loop 直接 generate / crawl / delete / publish | 禁止；只许产 `WorkflowRequest` |
| 抄 AGPL（LingChat / SANP）进 MIT 树 | 禁止 |
| 窥屏 / 键鼠钩子 / God Agent | 禁止 |
| 把 TTS 和记忆合成一个木桶项 | 禁止 |
| 永久取消 v1.9 | 禁止 |

用户已明确：

- Pixiv「不着急，绕过账号来升级」→ `WIN-013` = `deferred_by_user`（D-011）
- 聊天里出现过真实 NovelAI Token。**不要保存、不要回显、不要拿去打官方 API。应视为已泄露，建议用户轮换。**

---

## 4. 分支与 PR

| Worker | 分支 | Draft PR | 交付 | 状态 |
|---|---|---|---|---|
| Lead | `cursor/cloud-top-tier-integration-f036` | #3 | 本检查点全部工作 | draft，不要合 main |
| W0 | `cursor/cloud-w0-phase0-f036` | #7 | `W0_REVIEW.md` | 已审入集成 |
| W1 | `cursor/cloud-w1-nai-core-f036` | #8 | NAI compile snapshots / `W1_NAI_AUDIT.md` | 已审入集成；分数过期 |
| W2 | `cursor/cloud-w2-gallery-f036` | #9 | `GALLERY_INDEX_DESIGN.md` | 已审入集成 |
| W3 | `cursor/cloud-w3-agent-kernel-f036` | #6 | catalog projection | 已审入集成 |
| W4 | `cursor/cloud-w4-quality-f036` | #5 | `W4_QUALITY_AUDIT.md` | 已审入集成 |

历史：

- Upgrade PR #2 / `cursor/cloud-top-tier-integration-6d7e`：上一轮 v1.4 绑定 run 的延续源。本轮在 Upgrade 仓继续。
- Upgrade PR #1：Pixiv provider presets，无关。

Worker 分支不要单独合 `main`。`W1_NAI_AUDIT.md` / `W0_REVIEW.md` 里的旧分数（img2img=3.0、HTTP 恒 generate）**过期**，以 `CAPABILITY_MATRIX.md` 为准。

本检查点关键提交：

| SHA | 说明 |
|---|---|
| `9f4ce2a` | 画布、图库 HTTP、kernel chat、v1.9、诚实修 gate |
| `543999e` | 测试锁 + 本机 1145 通过记录 |
| `b1413e9` | 初版检查点报告（不是完成证明） |
| `c9efd74` | 云端阻断项修复 + 反例测试 |

---

## 5. 本检查点开工前的 CI

Draft PR #3 在 tip `ad83173` 上 Windows CI **红**：

https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/actions/runs/31873678878

| 失败 | 原因 | 诚实修法（未降门槛） |
|---|---|---|
| `tests/test_gallery_index.py` | Windows 上 SQLite 未关，`TemporaryDirectory` 删不掉 `gallery.db`（WinError 32） | 在 `with` 块内 `db.close()` |
| `tests/test_product_quality_gate.py` `p1 != 0` | `db.py` 因 `incremental_index` 涨到 1012 行 | 方法挪到 `gallery_index.run_incremental`；`db.py` 现 981 行 |
| 本机 POSIX 另见 Regression Guard | Guard 调 `python`，本 VM 只有 `python3` | `check_regression_guards.js` 回退 `python3` / `python` |

**没有**删除测试，**没有**改 `test_product_quality_gate.py` 的 `p1 == 0`。

---

## 5.1 本轮修复的云端阻断项（反例已锁）

上一版检查点报告**不是完成证明**。下面 8 项已在本轮修掉，每项都有反例测试。

| 阻断 | 修法 | 反例 |
|---|---|---|
| `resolve_work_image_path` 绝对路径绕过目录边界 | 绝对/相对都走 `gallery_index.resolve_index_image_path`；必须落在 `images_dir` / `DATA_DIR` / `DATA_DIR/images` | `/tmp/evil.png`、`../../../etc/passwd`、`\\x00` → `None`；source-image 400；索引不打开越界文件 |
| `ToolExecutor` timeout 被 `shutdown(wait=True)` 拖住 | 不用 context manager；`shutdown(wait=False, cancel_futures=True)` | `timeout_ms=50` + `sleep(1)`，`monotonic` 耗时 `>=0.04` 且 `<0.4`，`data=={}` |
| inpaint 原图与 mask 像素尺寸不一致 | compile 侧 `align_inpaint_mask`（NEAREST 缩到原图）；非 PNG 占位符保持原样；UI 从同一 canvas 导出 image+mask | 64×64 图 + 16×16 mask → parameters.mask 解码为 64×64；`"base64-or-bytes"`/`"base64-mask"` 回归不变 |
| `companion_state` 读改写无锁 | 模块级 `RLock`，propose/confirm/handoff/quiet/ack/mark_delivered 在锁内 load-mutate-save | 20 线程同时 `propose_memory`，JSON 不坏，条数=20 |
| quiet hours 未用配置时区 | `timezone=="local"` 用系统 tz，否则 `ZoneInfo`，失败回退 UTC；`now.astimezone(tz)` 再比 HH:MM | `Asia/Tokyo` 22:00–23:00 + `2026-08-15 13:30 UTC`（JST 22:30）为静默；同一时刻 UTC 钟不是 |
| 主动事件缺 dedupe / TTL / ack | 稳定 key；`acks[{key,at,ttl_sec}]` 默认 6h；`deliver=1` 与 `POST /api/companion/events/ack` 按 key ack | 未 ack 可再投；ack 后不再投；TTL 过期后可再投 |
| 已确认记忆未在 `request_plan` 前注入 | `planner_memory_context()` 在 `chat_json` **之前**写入 `confirmed_preferences` 和 system prompt；过滤 Token/Cookie/密码/路径；`planning.py` 仍零 import tooling | mock `chat_json`：有「竖图优先」，无 `pst-` / cookie / 用户路径 |
| 图库索引接口无批量上限 | `MAX_INCREMENTAL_WORK_IDS=200`，`MAX_INCREMENTAL_ITEMS=500`；超限 HTTP 400；全量截断 `truncated=true`；duplicates/similar 封顶 | 201 个 work_ids → 400；3 个 → 200；约 30 张小图规模行为（**不是** 10k/100k） |

Windows、真实 NAI Token、真实大图库：**本轮仍未验证，不要写成已完成。**

---

## 6. 决策（本检查点新增）

| Id | 选择 |
|---|---|
| D-001…D-014 | 见 `DECISIONS.md`；本轮不重做 |
| D-012 | 同一客户端编译 img2img / infill（覆盖 D-009 的 HTTP 冻结） |
| D-013 | 增量索引在现有 gallery SQLite；无第二任务库 |
| D-014 | 先扩 kernel，不 import `planning.py` |
| **D-015** | 四条 additive 图库 HTTP；不改 `/api/ai_works_search` JSON；入口是 `run_incremental` |
| **D-016** | `/app` + 经典 Studio 画布；`GET /api/studio/source-image`；仍走 `/api/nai/generate` |
| **D-017** | v1.6/v1.7 门槛通过后，经 `tool_loop_bridge` / `chat.py` 接入；`planning.py` 仍零 import |
| **D-018** | v1.9 记忆/交接/防打扰落地；TTS 拆成非核心行，不进木桶；禁止窥屏/钩子/God Agent |

D-013 原文「本波无 HTTP」已被 D-015 覆盖。D-014「不接聊天」已被 D-017 覆盖（接的是 chat，不是 planning）。

---

## 7. 已落地工程

### 7.1 NAI compile（上一波，仍有效）

单一客户端：

```
nai_char.build_generate_payload
  → nai_char_modules/generation.py
  → nai_api.generate_image
  → nai/generate.py
  → POST /ai/generate-image
```

| 输入 | HTTP `action` |
|---|---|
| 仅 `reference_image_multiple` | `generate`（Precise Reference） |
| 仅 `image`，无 mask，无显式 img2img | `generate`，`image` 进 `unsupported_fields` |
| 显式 `img2img` + `image` | `img2img` |
| `mask`+`image`，或显式 inpaint/infill + `image` | `infill` |
| Vibe 各键 | 不编译，进 `unsupported_fields` |
| 未知厂商键 | 不发送，进 `unknown_fields` |

默认 `force_free=True`。有 image / reference / mask 则 `free_eligible=false`。

测试：`tests/test_nai_generate_compile.py`、`tests/test_nai_param_snapshots.py`。

### 7.2 Studio 画布（本波）

- `GET /api/studio/source-image?work_id=&page_index=&gallery_id=`
  - 只读本库已下载原图
  - 返回 compile 用的 **raw PNG base64**（无 `data:` 前缀）、宽高、thumb
  - 路径限制在 gallery `images_dir` / `DATA_DIR` 内
- `/app`：`frontend/src/pages/StudioPage.tsx`
  - 模式：txt2img / img2img / inpaint
  - 从作品加载或本地文件
  - inpaint 在 overlay canvas 上画白笔 → mask PNG
  - `currentComment()` 写入 `action` / `image` / `mask` / `strength` / `noise`
- 经典：`web/studio.html` + `web/studio.js` + `web/studio.css` 同样能力
- 生成仍 `POST /api/nai/generate`，`frozen_comment: true`
- UI 明确提示：有图输入不是免费标准路径，可能消耗 Anlas
- **没有**付费官方 API 往返

测试：`tests/test_studio_canvas.py`、`tests/test_studio_workbench.py`。

### 7.3 图库索引 + HTTP（本波）

库：`gallery_index.py`

- 表仍在**现有** per-gallery SQLite：`gallery_index_files`、`gallery_image_hashes`
- 脏集增量 FTS（走已有 `_sync_work_fts` / `_sync_prompt_fts`）
- `rebuild_fts` 仍是 repair
- 精确 sha256、本地 dHash / pHash
- embed = `local_none`，不出网
- 入口：`gallery_index.run_incremental(db, ...)`（**不在** `db.py`）

HTTP（additive，不改搜索 JSON）：

| 方法 | 路径 |
|---|---|
| GET | `/api/gallery/{gallery_id}/index/status` |
| POST | `/api/gallery/{gallery_id}/index/incremental` |
| GET | `/api/gallery/{gallery_id}/duplicates?kind=exact\|near` |
| GET | `/api/gallery/{gallery_id}/similar?work_id=&page_index=&limit=` |

**未做**：虚拟相册、批量移动 preview/commit/restore、embedding。

`scripts/bench_gallery.py` 只是合成内存微基准。**禁止**写成 10k/100k。

测试：`tests/test_gallery_index.py`、`tests/test_gallery_index_http.py`。

### 7.4 v1.6 / v1.7 门槛审查

全文：`docs/top-tier-upgrade/GATE_REVIEW.md`。

| Gate | 云端结论 |
|---|---|
| v1.6 compile + 画布 | PASS（未付费真机出图） |
| v1.7 索引 + HTTP | PASS（非 10k 声明） |
| v1.8 kernel → chat | 上述通过后才允许 |
| 合 main / Release / 真 Token | 禁止 |

### 7.5 Tool Kernel 安全接入聊天

- 新：`butler/tool_loop_bridge.py`
- `butler/chat.py`：`compile_nai_preview` / `gallery_index_preview` 走 `ToolExecutor`（超时、分台鉴权、keyed 幂等）
- `butler/auto_exec.py`：同一条 preview 路径，给 LangGraph auto 节点用
- `generate_image` 等付费/破坏性名字若进 bridge，只产 `WorkflowRequest`，**不执行**
- 现有 confirm 工单路径未拆掉
- **`butler/planning.py` 零 import `butler.tooling`**（`tests/tooling/test_kernel_tools.py` 锁住）
- 分台：`gallery_index_preview` 双方可共享；`compile_nai_preview` 仅凑企鹅

### 7.6 v1.9 主动角色（无 TTS 木桶）

- `butler/companion_state.py` → `data/companion_state.json`（已被 `data/*` gitignore）
- 记忆：`propose` → 用户 `confirm` 后才跨会话复述；未确认不召回
- 禁止来源：`screen` / `keyhook` / `mousehook` / `god_agent` / `keylogger`
- 交接：只允许 `sakiko` ↔ `tomori`，带已确认偏好摘要
- 防打扰：静默时段、每小时上限、最小间隔；不自动强弹侧栏
- 主动事件只来自本机产品信号：Token 未配、待生成队列、索引脏集、待确认记忆、未读交接
- TTS：`public_state.tts.core = false`，未实现，不进木桶

HTTP：

| 方法 | 路径 |
|---|---|
| GET | `/api/companion/state` |
| POST | `/api/companion/memory/propose` |
| POST | `/api/companion/memory/confirm` |
| POST | `/api/companion/memory/forget` |
| POST | `/api/companion/handoff` |
| POST | `/api/companion/quiet` |
| GET | `/api/companion/events` |

UI：`web/shared/companion-dock.js`、`frontend/src/pages/ButlerPage.tsx`。

测试：`tests/test_companion_v19.py`、`tests/test_companion_dock_ui.py`。

### 7.7 后处理 / PNG / 质量（上一波，仍有效）

- 无 ANR：`mosaic:unavailable`，Lanczos 超分继续（`post.pipeline` = 6.0）
- PNG：嵌入 Comment 保留未知字段；无 text chunk 回退 stealth；拒 Comfy
- POSIX skip Windows-shell / DPAPI（D-003 / D-007）
- 环境无 NAI secret

---

## 8. 能力分（诚实，不是营销）

评分：0 无，5 通路弱于对标，8 对本产品可生产，10 有证据的领先。  
木桶 = **core=Y 的最低分**。

当前木桶：**6.0**（`post.pipeline` 与 `assist.proactive_events`）  
TTS（`assist.tts`）core=N，**不进木桶**。

| capability_id | core | 分 | 含义 |
|---|---|---:|---|
| `post.pipeline` | Y | **6.0** | 无 ANR 超分可用；打码仍靠可选 ANR |
| `assist.proactive_events` | Y | **6.0** | 本地信号 + 防打扰；不自动强弹 |
| `assist.memory_confirmed` | Y | 6.5 | 须用户确认才复述 |
| `search.visual_similar` | N | 6.5 | HTTP 有了；非 10k |
| `assist.tool_loop` | Y | 7.0 | chat 只跑 preview |
| `ingest.local_drop_nai_only` | Y | 7.0 | `/app` 图库页无拖入 |
| `gen.studio_frozen_txt2img` | Y | 7.0 | 付费闸门在；未做真机出图 |
| `publish.pixiv_browser` | Y | 7.0 | 用户 defer 账号 |
| `assist.split_desks` | Y | 7.0 | 分台是长板，不要合成单角色 |
| `search.fts_works_prompt` | Y | 7.5 | HTTP 有了；无 10k 真机 |
| `gen.img2img_inpaint_canvas` | Y | 7.5 | 画布已接；未付费真机 |
| `restore.png_stealth_v4` | Y | 8.0 | 未知字段可回填 |
| `start.one_click_launch` | Y | 8.0 | 云端无法真机验证 |
| `gen.cancel_balance_error` | Y | 8.0 | 缺 UI 取消 |
| `recover.generation_unknown` | Y | 8.0 | 崩溃 ≠ 没扣费 |
| `start.loopback_trust` | Y | 9.0 | 已是安全基线 |
| `assist.tts` | N | 0.0 | 未做，不扣核心分 |
| `lineage.recipe_object` | N | 2.0 | 未做 |

**不要把 7.5 的画布说成 8.0 的付费真机完成。不要把合成 bench 说成 10k。不要把 TTS=0 当成 v1.9 取消。**

---

## 9. 测试（Linux Cloud VM）

```
1155 passed, 68 skipped, 0 failed, 127 subtests
product_quality_gate: p0=0 p1=0 p2=0
scripts/scan_sensitive.py --git-candidates --content-only: clean
```

本轮新增/加锁的反例主要在：`tests/tooling/test_executor_timeout.py`、`tests/test_studio_canvas.py`、`tests/test_nai_generate_compile.py`、`tests/test_companion_v19.py`、`tests/test_planner_memory.py`、`tests/test_gallery_index.py`、`tests/test_gallery_index_http.py`。

命令（PATH 上常常没有 `python`）：

```bash
python3 -m pip install -r requirements.core.lock.txt pytest langgraph langgraph-checkpoint-sqlite aiosqlite
python3 -m compileall -q -x "runtime|\.venv|node_modules|data" .
python3 -m pytest -q --ignore=tests/test_pixiv_selector_probe.py
python3 scripts/product_quality_gate.py --json
python3 scripts/scan_sensitive.py --git-candidates --content-only
python3 scripts/bench_gallery.py --count 1000 --repeats 20
python3 scripts/check_windows_scripts.py
```

改 `frontend/src` 之后：

```bash
npm --prefix frontend run build
python3 scripts/asset_versions.py
```

Windows 全量：`scripts/verify.ps1` 或 `scripts/run_tests_windows.ps1`。诊断：`scripts/doctor_windows.ps1`。

---

## 10. 明确未做 / 不能假装完成

1. Windows `WIN-001`…`015` 真机：一键启动、打包、DPAPI、Defender、Live2D、大图库、junction
2. `WIN-012` 真实 NAI 出图（未授权）
3. `WIN-013` Pixiv 登录/发布（用户 defer）
4. 虚拟相册 / 批量移动 preview-commit-restore
5. TTS / 情感语音（故意不进木桶，不是取消 v1.9）
6. Studio 生成任务的 UI 取消按钮
7. `/app` 图库页拖入
8. 统一配方对象 `lineage.recipe_object`
9. 合 `main`、发 Release、顶尖声明
10. 10k / 100k 图库成绩
11. **Windows 真机、真实 NAI Token、真实大图库：本轮明确未验证**

---

## 11. 后续允许 / 禁止

### 允许（需用户明确下令）

- Windows 真机跑 `PENDING_LOCAL_WINDOWS.md`
- 用户书面授权后做 **一次** 受控免费/限次 NAI（`WIN-012`）
- 按设计补相册 / 移动 journal（additive，不改搜索 JSON）
- 后处理打码在无 ANR 时的替代方案（不要假装有 ANR）

### 禁止（即使用户说「继续升级」也不要自己做）

- 合 `main` / 发 Release / 改 LICENSE
- 连接 Manga / Phone
- 把 tooling 写入 `planning.py`
- 窥屏 / 键鼠钩子 / God Agent
- 把 TTS 和记忆合成一个木桶项，或永久取消 v1.9
- 使用或持久化任何聊天里的 Token
- 为了变绿而改 `test_product_quality_gate` 门槛或删测试
- 把 `scripts/bench_gallery.py` 写成 10k/100k 成绩
- 重做 Phase 0 审计
- 发明第二套 NAI 客户端、任务库、图库索引或权限系统

---

## 12. 给下一任的粘贴指令

```
执行模式继续为 CLOUD_WEB，除非本机已按 HANDOFF 切到 LOCAL_WINDOWS。
完整读取 docs/top-tier-upgrade/CLOUD_CHECKPOINT_REPORT.md，以及
GATE_REVIEW.md、RUN_STATE.json、STATUS.md、OWNERSHIP.md、
DECISIONS.md、CAPABILITY_MATRIX.md、PENDING_LOCAL_WINDOWS.md。
CLOUD_COMPLETE_REPORT.md 是上一波交接，后半过期，以本检查点报告和远程 tip 为准。
唯一仓库 h1neolzr7f/NaiXueZhang-Studio-Upgrade。
不要连接 Manga。不要重做 Phase 0。
checkout cursor/cloud-top-tier-integration-f036（以远程 tip 为准）
v1.6 画布 / v1.7 HTTP / v1.8 chat 接入 / v1.9 记忆已在云端落地。
不要把 tooling 写入 planning.py。
不要把 TTS 和记忆合成一个木桶项。v1.9 不得永久取消。
不要合并 main、不要发 Release、不要用真实 NAI Token。
Windows WIN-001..015 留给本地接管。
```

---

## 13. 关键代码入口

| 主题 | 文件 |
|---|---|
| NAI compile | `nai_char_modules/generation.py` |
| NAI HTTP | `nai/generate.py`、`nai_api.py` |
| PNG 回填 | `nai_char_modules/snapshots.py`、`nai_image_metadata.py` |
| 后处理 | `post_pipeline.py` |
| 图库索引 | `gallery_index.py`（`run_incremental`） |
| 图库 HTTP | `routes/gallery.py` |
| Studio 原图 | `studio_service.py`、`routes/studio.py` |
| `/app` 画布 | `frontend/src/pages/StudioPage.tsx` |
| 经典画布 | `web/studio.js`、`web/studio.html` |
| Tool kernel | `butler/tooling/` |
| 聊天接入 | `butler/tool_loop_bridge.py`、`butler/chat.py` |
| 计划器（仍不 import kernel） | `butler/planning.py` |
| v1.9 | `butler/companion_state.py`、`routes/butler.py` |
| 门槛审查 | `docs/top-tier-upgrade/GATE_REVIEW.md` |

---

## 14. 回滚

- 本检查点：关闭 Draft PR #3，或 `git checkout main` @ `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`
- 不要 force-push `main`
- 图库新表可 `DROP TABLE gallery_index_files; DROP TABLE gallery_image_hashes;`
- 停用画布：去掉 `/api/studio/source-image` 与两套 Studio 的 mode/canvas
- 停用 kernel 聊天：停止从 `chat.py` / `auto_exec.py` 调用 `execute_chat_action`
- 停用 v1.9：停掉 `/api/companion/*`，删除 `data/companion_state.json`
- 不要把 Worker 分支单独合进 `main`
