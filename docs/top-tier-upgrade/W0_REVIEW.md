# W0_REVIEW

Phase 0 只读复核。不改生产代码，不改 `CAPABILITY_MATRIX.md` / `COMPETITOR_BASELINE.md` / `NAI_PARAM_MATRIX.md` / `DECISIONS.md` / `STATUS.md`。本文件是 W0 唯一新增交付。

## C26 交付头

| 字段 | 值 |
|---|---|
| worker | W0 |
| role | 能力矩阵与竞品基线只读复核（并行，不重做 Lead 文档） |
| repository | `h1neolzr7f/NaiXueZhang-Studio-Upgrade` |
| branch | `cursor/cloud-w0-phase0-f036` |
| maps_to | `cloud/w0-phase0` |
| base | `main` @ `008de38ad4dc6c8afbf0ec32ae411cd85685ac02` |
| reviewed_sha | `4d8dbea13eb166c4351c4e31f55ecc658bd40c6d` |
| execution_mode | `CLOUD_WEB` |
| phase | `PHASE_0`（对照 Wave 2 已落地内核，不启动 v1.6 UI） |
| model | requested Grok 4.6 xhigh Fast；actual `cursor-grok-4.6-high-fast`；xhigh 不可单独选择，已记录 |
| scope | 读矩阵/基线/参数表/决策/状态；对照源码核验最短木板；只新增本文件 |
| files_changed | `docs/top-tier-upgrade/W0_REVIEW.md` only |
| tests | 只读复核后跑 compile lock + tooling 子集（见文末） |
| benchmarks | 无新数字；不声称 10k/100k |
| depends_on | Lead 文档树 + Wave 2 已提交的 compile/tooling 内核 |
| shared_file_conflicts | 无。不改 Lead/W1/W2/W3/W4 租约文件 |
| windows_pending | WIN-001..015 仍 queued；本复核不 consummate |
| safe_rollback | 删除本分支；不碰 `main`、不关 Lead Draft PR #3 |
| lead_review | 请 Lead 采纳分数/决定，由 Lead 决定是否回写矩阵 |
| out_of_scope | `Manga-Editor-Desu-NAI`、`NaiXueZhang-Studio-Phone`、真实 NAI Token、合并 main、发 Release、改 LICENSE |

## 结论

**三块最短木板仍然是：**

1. `gen.img2img_inpaint_canvas` **3.0** — **implement**
2. `post.pipeline` **3.0** — **replace**
3. `assist.memory_tts_emotion` **4.0** — **defer**；下一可实施内核是 `assist.tool_loop` **5.0** — **implement**（尚未接入聊天）

**barrel_lowest_score 仍为 3.0。** 核心行没有比 3.0 更短的木板。非核心 `search.visual_similar` / `lineage.recipe_object` 仍为 2.0，但不进桶。

Wave 2 已把 img2img/inpaint **报告出来**、把 Tool Loop **超时/取消/四轮上限**做完，但没有把画布、后处理引擎或聊天接入补上。因此矩阵分数不必上调，也不必下调。

STATUS 的 Next 仍然正确：本波不要开 img2img UI，也不要把 tooling 接入 `planning.py`。

## 三块最短木板

### 1. gen.img2img_inpaint_canvas

| 项 | 值 |
|---|---|
| user_journey_step | 生成 |
| core | Y |
| benchmark_project | NAIWeaver |
| score | **3.0**（维持） |
| target | 8.0 |
| decision | **implement** |
| reason | 路径存在但弱于竞品：能从图库回填 txt2img，没有蒙版画布，HTTP `action` 恒为 `generate` |
| acceptance | 能从本库图打开 img2img 并回填 |

**当前行为（源码）**

- `/app` Studio 只有冻结 txt2img：Prompt / UC / 尺寸 / vibe URL / 角色参考 URL。无 `action` 切换，无 mask 画布，无取消按钮。`frontend/src/image.ts` 的 canvas 只做缩略压缩，不是 inpaint。
- 经典 `web/studio.js` 同样没有 img2img/inpaint 控件。
- `nai_char_modules/generation.py`：`build_generate_payload` 写死 `"action": "generate"`；`image`/`mask` 进 `unsupported_fields`，不进 `parameters`。`requested_action` 可记录 `img2img`/`inpaint`/`infill`。
- `nai/generate.py` 把 compile 的 `action` 原样放入 HTTP body，因此生产请求仍是 txt2img。
- D-009 已冻结：未通过测试锁前不得改 HTTP action，也不得开第二套 NovelAI 客户端。

**证据**

- `frontend/src/pages/StudioPage.tsx`（生成只 POST `/api/nai/generate`，无 mask/action UI）
- `nai_char_modules/generation.py` L128–157, L286–294
- `nai/generate.py` L329–339
- `tests/test_nai_generate_compile.py`：`test_mask_and_image_keep_txt2img_action_until_img2img_lands`、`test_unknown_and_uncompiled_fields_are_reported_not_dropped`
- `docs/top-tier-upgrade/NAI_PARAM_MATRIX.md`：img2img/inpaint `Compiled into HTTP?` = no
- `docs/top-tier-upgrade/DECISIONS.md` D-009

**建议**

- **implement**（v1.6，W1 编译层先于 UI）：在现有 `nai_char.build_generate_payload` → `nai_api.generate_image` 上增加专用 img2img/inpaint compile；先锁当前 txt2img payload 测试，再改 `action`。
- **exclude**：第二套 NovelAI 客户端；静默把 image/mask 当 generate 发出。
- **defer**：本 Wave / 本 Cloud 回合的 Studio 蒙版画布（STATUS 已写明）。
- 回填范围应对齐验收：本库图 → prompt/uc/seed/尺寸/原图；mask 与 strength 进编译后再开画布。

### 2. post.pipeline

| 项 | 值 |
|---|---|
| user_journey_step | 后处理 |
| core | Y |
| benchmark_project | SANP / NAI-Utility-Tool |
| score | **3.0**（维持） |
| target | 7.0 |
| decision | **replace** |
| reason | Lanczos 超分可用，但打码硬绑外挂 ANR；无引擎声明；ANR 路径写死个人 Windows 目录 |
| acceptance | 无 ANR 时超分仍可用且声明引擎 |

**当前行为（源码）**

- 流水线：超分 → 打码(可选 ANR) → 清元数据。超分实现是 Pillow Lanczos（`_upscale_lanczos`），步骤只记 `upscale:2x`，不声明引擎名。
- 打码：`mosaic_runtime_status` / `_mosaic_via_anr` 要求 `plugins/anr_plugin_auto_mosaics`。默认 `mosaic.enabled=False` 时超分可独立跑。
- 一旦打码开启且 ANR 不在：`need_mosaic` 直接 `raise RuntimeError`，整张流水线失败（超分文件可能已写出，但 `*_final` 不完成）。
- ANR 候选根含 `E:/ai批量生图/Auto-NovelAI-Refactor` 与桌面路径（HANDOFF 已记）。
- `/app` Pipeline 页只有开关，文案把 ANR 细节指回经典 `/pipeline`。无 ONNX/DirectML 引擎选择。WIN-008 仍 queued。

**证据**

- `post_pipeline.py` L1, L42–49, L274–344, L812–815, L1049–1075
- `frontend/src/pages/PipelinePage.tsx` L130 附近（ANR 外链提示）
- `tests/test_architecture_upgrade.py`：`test_mosaic_runtime_status_does_not_import_detector`、上传路径强制 mosaic
- `docs/top-tier-upgrade/COMPETITOR_BASELINE.md`：SANP = replace ANR hard path；NAI-Utility-Tool = implement behavior, exclude source copy
- `docs/top-tier-upgrade/PENDING_LOCAL_WINDOWS.md` WIN-008

**建议**

- **replace** ANR 硬路径：无插件时超分必须成功并写出 `engine=lanczos`（或等价声明）。打码改为可选、失败可跳过并显式 `mosaic:skip(...)`，不要拖死超分验收。
- **implement** 后续 Windows ONNX/DirectML 超分行为（WIN-008），只学行为，不拷 GPL/AGPL 源码。
- **exclude**：把 ANR / SANP 源码迁入本 MIT 树；Cookie 直传；插件商店。
- **defer**：高质量超分硬件数字，直到同一台 Windows 真机记录引擎名。

### 3a. assist.memory_tts_emotion

| 项 | 值 |
|---|---|
| user_journey_step | 主动角色体验 |
| core | Y |
| benchmark_project | LingChat |
| score | **4.0**（维持） |
| target | 6.0 |
| decision | **defer** |
| reason | v1.9；Live2D 分台已有，无长期记忆 / TTS / 窥屏 |
| acceptance | 跨会话只复述已确认偏好 |

**当前行为（源码）**

- `web/shared/companion-dock.js`：Live2D 目录、问候、chips、`/api/butler/chat`。无 TTS、无 speechSynthesis、无跨会话记忆、无屏幕采集。
- `butler/planning.py`：一次性 JSON 计划器，不读历史偏好库。
- `nai_director.py` 的 `emotion` 是官方 Director 改表情，不是角色情感 TTS。
- AGENTS.md / D-004 / 竞品表：不做 God Agent、键鼠钩子、窥屏。

**证据**

- `web/shared/companion-dock.js` L1–64, L67+
- `butler/planning.py` L1–67
- `docs/top-tier-upgrade/COMPETITOR_BASELINE.md` LingChat 行
- `docs/top-tier-upgrade/DECISIONS.md` D-004

**建议**

- **defer** 到 v1.9：已确认偏好的跨会话复述；可选本地 TTS。
- **exclude**：窥屏、键鼠钩子、God Agent、任意插件、把分台合成单角色。
- 不要为了追 LingChat 体验分而提前做记忆，以免打乱 v1.8 Tool Loop 闸门。

### 3b. assist.tool_loop（下一可实施内核，不是桶底）

| 项 | 值 |
|---|---|
| user_journey_step | Agent Tool Runtime |
| core | Y |
| benchmark_project | LingChat |
| score | **5.0**（维持；Wave 2 已计入超时/取消/loop_limit） |
| target | 9.0 |
| decision | **implement** |
| reason | 独立内核已建且有测试；`butler/planning.py` / HTTP / LangGraph 均未接入 |
| acceptance | 付费工具只产 WorkflowRequest |

**当前行为（源码）**

- `butler/tooling/`：`InteractiveLoop` 四轮上限，超限返回 `loop_limit` 不抛；`ToolExecutor` 超时、取消、schema、红线；非 interactive 工具只产 `WorkflowRequest`（`anlas_estimate=unknown`，`requires_confirmation=True`）。
- `rg InteractiveLoop butler/planning.py`：无命中。聊天仍走一次性计划器。
- 测试锁：付费 `generate_image` 不跑 handler。

**证据**

- `butler/tooling/loop.py` L10–63
- `butler/tooling/executor.py` L97–133, L200–220
- `butler/tooling/workflow_request.py`
- `tests/tooling/test_loop_limit.py`、`tests/tooling/test_workflow_request_not_executed.py`、`tests/tooling/test_executor_timeout.py`
- `butler/planning.py`（无 tooling import）
- `docs/top-tier-upgrade/OWNERSHIP.md`：W3 租约到 v1.8 integration

**建议**

- **implement**（v1.8，W3 只留在 `butler/tooling`）：保持独立内核；接入必须经 Lead 改 `planning.py`。
- **exclude**：Tool Loop 直接执行 generate / crawl / delete / publish；替换 LangGraph。
- **defer**：本 Wave 接入聊天（STATUS / NEXT_ACTION 已禁止）。

## 核心能力复验（是否仍短于上述三块）

对照 `CAPABILITY_MATRIX.md` 的 core=Y 行，源码抽查后 **全部维持原分**。没有新的更短木板。

| capability_id | 矩阵分 | 复验分 | decision | 源码要点 |
|---|---:|---:|---|---|
| start.one_click_launch | 8.0 | 8.0 | implement | `INSTALL.bat` / `START_GALLERY.bat` 仍在；云端未真机（WIN-001/002） |
| start.loopback_trust | 9.0 | 9.0 | exclude | 已是安全基线；不削弱 |
| ingest.local_drop_nai_only | 7.0 | 7.0 | implement | 经典拖入 + `parse_nai_image`；`/app` GalleryPage 无拖入 |
| search.fts_works_prompt | 6.0 | 6.0 | implement | `search.py` FTS 作品+Prompt；无语义 |
| restore.png_stealth_v4 | 7.0 | 7.0 | implement | `nai_image_metadata.py` 入库读 stealth；Studio 回填走 comment，丢 vibe/mask |
| gen.studio_frozen_txt2img | 7.0 | 7.0 | implement | `/api/nai/generate` + `force_free` 默认；付费闸门仍是长板 |
| **gen.img2img_inpaint_canvas** | **3.0** | **3.0** | **implement** | 见上 |
| gen.cancel_balance_error | 8.0 | 8.0 | implement | `generation_jobs` unknown / billing_uncertain；Studio 无取消按钮 |
| **post.pipeline** | **3.0** | **3.0** | **replace** | 见上 |
| publish.pixiv_browser | 7.0 | 7.0 | implement | Playwright；Butler 只准备草稿 |
| recover.generation_unknown | 8.0 | 8.0 | implement | `recovered_after_restart` + `can_retry` |
| assist.split_desks | 7.0 | 7.0 | exclude | `SAKIKO_TOOLS` 无 `generate_image`；执行期 `reject_foreign_tool` |
| **assist.tool_loop** | **5.0** | **5.0** | **implement** | 见上 |
| **assist.memory_tts_emotion** | **4.0** | **4.0** | **defer** | 见上 |

非核心（不进桶，确认未误当作最短生产闸门）：

| capability_id | 矩阵分 | 复验分 | decision |
|---|---:|---:|---|
| search.visual_similar | 2.0 | 2.0 | defer |
| lineage.recipe_object | 2.0 | 2.0 | implement（血缘，非当前桶底） |

## 桶

| 核心能力（验收总表） | 复验分 | 决定最低项的行 |
|---|---:|---|
| NAI 原生创作 | 3.0 | gen.img2img_inpaint_canvas |
| 批量生产 | 8.0 | gen.studio_frozen_txt2img / char-swap 预检 |
| 图库与资产复用 | 6.0 | search.fts_works_prompt |
| 后处理 | 3.0 | post.pipeline |
| 发布与恢复 | 7.0 | publish.pixiv_browser |
| 数据和付费安全 | 8.5 | recover.generation_unknown + P0 测试 |
| Agent Tool Runtime | 5.0 | assist.tool_loop |
| 主动角色体验 | 4.0 | assist.memory_tts_emotion |
| Windows 安装与上手 | 8.0 | 云端未真机 |
| 文档与可验证性 | 7.5 | 本目录已建立；本复核不改矩阵 |

**barrel_lowest_capability:** `gen.img2img_inpaint_canvas` / `post.pipeline`  
**barrel_lowest_score:** `3.0`

## 竞品基线复验

未克隆任何竞品源码。未连接 Manga。行为对照仍成立：

| Competitor | 矩阵决定 | W0 复验 | 备注 |
|---|---|---|---|
| NAIWeaver | implement subset | 维持 | 扩现有 compile；报告未编译 image/mask/vibe |
| Infinite Image Browsing | FTS/dup first；defer semantic；exclude SD/Comfy | 维持 | NAI-only 门仍在 `parse_nai_image` |
| SANP (AGPL) | replace ANR；exclude Cookie / 插件店 | 维持 | 只学行为 |
| LingChat (AGPL) | implement ideas in `butler/tooling`；exclude God Agent | 维持 | 不替换 LangGraph |
| Langbai | implement install/doctor；exclude 多供应商/漫画分镜 | 维持 | Windows first |
| NyaNovel | exclude as replacement | 维持 | 只偷信息层级 |
| NAI-Utility-Tool (GPL) | implement behavior；exclude source copy | 维持 | MIT/GPL 边界 |
| Manga-Editor-Desu-NAI | exclude / OUT_OF_SCOPE / SUPERSEDED_OUT_OF_SCOPE | **维持，且本 Worker 未连接** | D-006 |

## NAI 参数矩阵复验

与 `NAI_PARAM_MATRIX.md` 一致，无上调理由：

| Field / mode | Compiled into HTTP? | 复验 |
|---|---|---|
| V4.5 Full / Curated / V4 | yes | 维持 |
| width/height/sampler/steps/scale/seed | yes | 维持 |
| Precise Reference 数组 | yes，但 `action=generate` | 维持 |
| Vibe Transfer | no，进 `unsupported_fields` | 维持 |
| img2img / inpaint image/mask/action | no | 维持；最短木板 1 |
| Enhance / Director | 独立路径 | defer 维持 |
| unknown vendor keys | 进 `unknown_fields` | Wave 2 已测 |

## 决策对齐

| ID | 与最短木板关系 | W0 |
|---|---|---|
| D-001 | 只写 Upgrade | 遵守；未碰 v1.4 / Manga |
| D-004 | 唯一 generate 客户端；付费只产 WorkflowRequest | 遵守 |
| D-006 | Manga / Phone OUT_OF_SCOPE | 遵守 |
| D-008 | 不重做 Phase 0、不改 main | 本文件是复核，不是重写矩阵 |
| D-009 | HTTP action 保持 generate | **仍是 img2img 木板的正确约束** |

## 给 Lead 的 implement / replace / exclude / defer

按优先级，不扩大本 Worker 范围：

1. **implement** `gen.img2img_inpaint_canvas`（v1.6 / W1 编译层）— 桶底之一。先测后改 action。
2. **replace** `post.pipeline` ANR 硬依赖 — 桶底之二。先声明 Lanczos，无 ANR 超分必须可用。
3. **implement** `assist.tool_loop` 接入（v1.8 / Lead+W3）— 下一可实施内核。现在不要接入 `planning.py`。
4. **defer** `assist.memory_tts_emotion` 到 v1.9；**exclude** 窥屏/钩子/God Agent。
5. **exclude** 继续：Manga、第二客户端、AGPL 拷贝、Cookie 上传、合成单角色、削弱付费/unknown 隔离。
6. **defer** `search.visual_similar`；血缘 `lineage.recipe_object` 可 implement 但不抢桶底。

**不要**因为本复核去改 `CAPABILITY_MATRIX.md`。分数无变化，Lead 不必重写；若要标注 “W0 confirmed @ 4d8dbea”，由 Lead 执笔。

## W0 未做 / 禁区

- 未改任何生产代码、测试、脚本、许可证、Release。
- 未改 Lead 独占文件，未改其他 Worker 租约文件。
- 未创建指向 `main` 的合并，未强推 `main`。
- 未使用真实 NAI Token，未发付费请求。
- 未连接、克隆、审计 `Manga-Editor-Desu-NAI`。
- 未启动 img2img UI，未把 tooling 接入聊天。

## 测试

复核提交后已跑（cloud-safe，无 Token）：

```text
python3 -m pytest -q tests/test_nai_generate_compile.py tests/tooling --ignore=tests/test_pixiv_selector_probe.py
28 passed in 1.22s
```

不跑 Windows cmd/DPAPI，不跑真实 NAI，不把合成 bench 写成 10k/100k。
