# Nai学长工作室 · 云端升级完整交接报告

**上一波（v1.6 compile / v1.7 库级索引 / v1.8 kernel）交接。后半节过期。**

当前权威报告：`docs/top-tier-upgrade/CLOUD_CHECKPOINT_REPORT.md`。以远程分支 tip 为准。

- 日期：2026-08-15（本文件写入提交 `0c46e12`）
- 执行模式：`CLOUD_WEB`
- 结论：**这是历史交接，不是当前完成证明。**
- 不要声称顶尖完成。不要合 `main`。不要发 Release。不要用真实 NAI Token。

---

## 0. 一句话结论

云端可完成的 Phase 0 + v1.6 compile/canvas + v1.7 gallery index/HTTP + v1.8 kernel→chat + v1.9 记忆/交接/防打扰 **已落地（检查点）**。

剩下的要 Windows 真机，或用户授权付费/Pixiv。TTS 不是核心木桶项。v1.9 没有永久取消。

下一刀主要在本地：

1. Windows `WIN-001`…`WIN-015`
2. 用户书面授权后的受控 NAI（`WIN-012`）

Pixiv `WIN-013` 用户已要求跳过。窥屏 / 键鼠钩子 / God Agent 仍然禁止。

---

## 1. 身份与指针

| 项 | 值 |
|---|---|
| 唯一实施仓 | `h1neolzr7f/NaiXueZhang-Studio-Upgrade` |
| 集成分支 | `cursor/cloud-top-tier-integration-f036` |
| 报告写入提交 | `0c46e12edf4d36aa12e28cb1de1bb9d831d138f0` |
| 以分支 tip 为准 | `git rev-parse origin/cursor/cloud-top-tier-integration-f036` |
| `main` 基线（未改） | `008de38ad4dc6c8afbf0ec32ae411cd85685ac02` |
| 集成 Draft PR | https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/3 |
| Lead run | https://cursor.com/agents/bc-6ecf51c6-e504-4cfe-85d6-9b8feaf5f036 |
| Cloud Build | [bld-20260815-c10799be-3d0d-41bd-8535-6eaedb553274](https://cursor.com/dashboard/cloud-agents/builds/bld-20260815-c10799be-3d0d-41bd-8535-6eaedb553274) READY |
| 环境 | [d93c0dbf-9877-11f1-ba66-0e7d0216e441](https://cursor.com/dashboard/cloud-agents/environments/e/d93c0dbf-9877-11f1-ba66-0e7d0216e441) 个人过渡 draft，无 NAI secret |
| 请求模型 | Grok 4.6 xhigh Fast |
| 实际模型 | `cursor-grok-4.6-high-fast`（xhigh 不可单独选，已记录） |

`Manga-Editor-Desu-NAI` 与 `NaiXueZhang-Studio-Phone` 均为 `OUT_OF_SCOPE` / `SUPERSEDED_OUT_OF_SCOPE`。冻结 v1.4 仓 `NaiXueZhang-Studio` 不是升级主干（D-001 / D-008）。

---

## 2. 先读这些文件（按顺序）

权威状态在仓库文档，聊天不是唯一来源。

1. `docs/top-tier-upgrade/CLOUD_CHECKPOINT_REPORT.md`（当前权威）
2. `docs/top-tier-upgrade/CLOUD_COMPLETE_REPORT.md`（本文件，历史）
3. `docs/top-tier-upgrade/RUN_STATE.json`
3. `docs/top-tier-upgrade/STATUS.md`
4. `docs/top-tier-upgrade/OWNERSHIP.md`
5. `docs/top-tier-upgrade/DECISIONS.md`
6. `docs/top-tier-upgrade/CAPABILITY_MATRIX.md`
7. `docs/top-tier-upgrade/NAI_PARAM_MATRIX.md`
8. `docs/top-tier-upgrade/GALLERY_INDEX_DESIGN.md`
9. `docs/top-tier-upgrade/CLOUD_PRS.md`
10. `docs/top-tier-upgrade/PENDING_LOCAL_WINDOWS.md`
11. `docs/top-tier-upgrade/HANDOFF_CLOUD_TO_WINDOWS.md`
12. `docs/top-tier-upgrade/NEXT_ACTION.md`
13. `AGENTS.md`

checkout：

```bash
git fetch origin cursor/cloud-top-tier-integration-f036
git checkout cursor/cloud-top-tier-integration-f036
git rev-parse HEAD
# 报告写入：0c46e12edf4d36aa12e28cb1de1bb9d831d138f0；以分支 tip 为准
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

用户已明确：

- Pixiv「不着急，绕过账号来升级」→ `WIN-013` = `deferred_by_user`（D-011）
- 聊天里出现过真实 NovelAI Token。**不要保存、不要回显、不要拿去打官方 API。应视为已泄露，建议用户轮换。**

---

## 4. 分支与 PR

| Worker | 分支 | Draft PR | 交付 | 状态 |
|---|---|---|---|---|
| Lead | `cursor/cloud-top-tier-integration-f036` | #3 | 集成本文件所述全部工作 | draft，不要合 main |
| W0 | `cursor/cloud-w0-phase0-f036` | #7 | `W0_REVIEW.md` | 已审入集成 |
| W1 | `cursor/cloud-w1-nai-core-f036` | #8 | NAI compile snapshots / `W1_NAI_AUDIT.md` | 已审入集成 |
| W2 | `cursor/cloud-w2-gallery-f036` | #9 | `GALLERY_INDEX_DESIGN.md` | 已审入集成 |
| W3 | `cursor/cloud-w3-agent-kernel-f036` | #6 | catalog projection | 已审入集成 |
| W4 | `cursor/cloud-w4-quality-f036` | #5 | `W4_QUALITY_AUDIT.md` | 已审入集成 |

历史：

- Upgrade PR #2 / `cursor/cloud-top-tier-integration-6d7e`：上一轮 v1.4 绑定 run 的延续源。本轮在 Upgrade 仓继续。
- Upgrade PR #1：Pixiv provider presets，无关。

Worker 分支不要单独合 `main`。

---

## 5. 文件所有权

Lead 独占，未到门槛不要改：

- `butler/store.py`
- `butler/workflow_runtime.py`
- `butler/planning.py`
- `butler/agents.py`
- `data/butler_catalog.json`
- LICENSE / VERSION / Release 脚本

租约：

| 路径 | 所有者 | 说明 |
|---|---|---|
| `nai/` `nai_api.py` `nai_char_modules/` | W1 | 唯一 NAI compile/transport |
| `gallery_*.py` `gallery_index.py` `db.py` `db_queries.py` `search.py` `generated_gallery.py` | W2 | 图库资产 + 增量索引 |
| `butler/tooling/` `tests/tooling/` | W3 | 独立内核，未接聊天 |
| `tests/` `scripts/*windows*.ps1` `scripts/bench_gallery.py` `docs/top-tier-upgrade/` | W4 / Lead | 质量与交接 |
| `frontend/` `web/` | 共享读；改 UI 需单独租约 | 双 UI |

**禁止把 tooling 接入 `planning.py`。门槛通过后只经 `tool_loop_bridge` / `chat.py` 接入。**

---

## 6. 决策一览

| Id | 选择 |
|---|---|
| D-001 | 实施仓绑定 Upgrade，不改冻结 v1.4 |
| D-002 / D-008 | 分支名 `cursor/cloud-*-f036`；本轮从 6d7e 树继续，不重做 Phase 0 |
| D-003 / D-007 | POSIX 跳过 Windows-shell / DPAPI / cmd 用例，不改生产语义去变绿 |
| D-004 | 冻结 `WorkRef`、`/api/ai_works_search` JSON、唯一 `generate_image` |
| D-005 | Windows 脚本别名：`doctor_windows.ps1` 等 |
| D-006 | Manga / Phone 出范围 |
| D-009 | 先报告 `requested_action` / `unsupported_fields` / `unknown_fields` |
| D-010 | 无 ANR 不打断 Lanczos 超分 |
| D-011 | 本波跳过 Pixiv/账号；不持久化聊天 Token |
| D-012 | **在同一客户端上编译 img2img/infill**（满足规则后覆盖 D-009 的 HTTP 冻结） |
| D-013 | 增量索引加在现有 gallery SQLite；无第二任务库；本波无 HTTP 路由 |
| D-014 | 只扩 `butler/tooling`；不 import `planning.py` |

---

## 7. 已落地工程

### 7.1 D-012 NAI compile

单一客户端：

```
nai_char.build_generate_payload
  → nai_char_modules/generation.py
  → nai_api.generate_image
  → nai/generate.py
  → POST /ai/generate-image
```

禁止再写第二套 NovelAI 出图客户端。`nai/generate.py` 已把 `payload_info["action"]` 原样放进 POST body。

| 输入 | HTTP `action` | 说明 |
|---|---|---|
| 仅 `reference_image_multiple` | `generate` | Precise Reference |
| 仅 `image`，无 mask，无显式 img2img | `generate` | `image` 进 `unsupported_fields` |
| 显式 `img2img` + `image` | `img2img` | `image` / `strength` / `noise` 进 parameters |
| `mask`+`image`，或显式 inpaint/infill + `image` | `infill` | NovelAI 的 inpaint 名是 infill |
| Vibe 各键 | 不编译 | 进 `unsupported_fields` |
| 未知厂商键 | 不发送 | 进 `unknown_fields` |

默认 `force_free=True`。有 image / reference 则 `free_eligible=false`。

锁定测试：

- `tests/test_nai_generate_compile.py`
- `tests/test_nai_param_snapshots.py`
- `tests/test_nai_char_module_contracts.py`

### 7.2 PNG 回填

- 嵌入 Comment 保留未知字段
- 无 text chunk 时，`comment_from_png` 回退 `parse_nai_image`（含 stealth）
- Comfy 仍拒绝
- 测试：`tests/test_nai_png_restore.py`
- **没有付费 API 往返**

### 7.3 D-010 后处理

无 ANR 不再整条失败：记 `mosaic:unavailable`，超分 `upscale:2x` + `upscale_engine=lanczos`，元数据继续。

测试：`tests/test_post_pipeline.py::PostPipelineAnrOptionalTests`

`post.pipeline` = 6.0。

### 7.4 D-013 图库索引

`gallery_index.py` 加在**现有** per-gallery SQLite：

- 脏集增量 FTS（走已有 `_sync_work_fts` / `_sync_prompt_fts`）
- `rebuild_fts` 仍是 repair
- 精确 sha256 重复
- 本地 dHash / pHash 相似
- embed 默认 `local_none`，不出网
- `Database.incremental_index(...)` 为入口
- **不改** `/api/ai_works_search` JSON
- **本波无 HTTP 路由**
- **不是** 10k/100k 声明

测试：`tests/test_gallery_index.py`

`scripts/bench_gallery.py` 只是合成内存微基准。任何数字必须带：

> synthetic in-memory micro-bench; not a Windows 10k/100k claim; see `BENCHMARKS.md` and `PENDING_LOCAL_WINDOWS` WIN-010.

设计全文：`GALLERY_INDEX_DESIGN.md`。虚拟相册、批量移动 preview/commit/restore、embedding 未实现。

### 7.5 D-014 tooling kernel

- `butler/tooling/kernel_tools.py`：`compile_nai_preview`、`gallery_index_preview`
- executor：keyed 幂等、output schema 校验
- 已有：四轮上限、超时、取消、付费/破坏性只产 `WorkflowRequest`
- catalog 投影只读，不改 `data/butler_catalog.json`
- **`planning.py` 零 import**
- 测试：`tests/tooling/test_kernel_tools.py` 及既有 `tests/tooling/`

### 7.6 云端质量基线

- POSIX skip：Windows-shell / DPAPI / cmd（D-003 / D-007）
- `.cursor/environment.json`：`requirements.core.lock.txt` + pytest + langgraph + langgraph-checkpoint-sqlite + aiosqlite
- `scripts/check_windows_scripts.py`：启动器禁 Token 赋值

---

## 8. 能力分（诚实，不是营销）

评分：0 无，5 通路弱于对标，8 对本产品可生产，10 有证据的领先。  
木桶 = **core=Y 的最低分**。

当前木桶：**4.0**（`assist.memory_tts_emotion`，v1.9 defer）  
下一块能继续抬的：**6.0**（`gen.img2img_inpaint_canvas` compile 有了，Studio 画布没有）

| capability_id | core | 分 | 目标 | 含义 |
|---|---|---:|---:|---|
| `assist.memory_tts_emotion` | Y | **4.0** | 6.0 | 木桶最低；v1.9 defer；禁止窥屏 |
| `gen.img2img_inpaint_canvas` | Y | **6.0** | 8.0 | compile 有了，Studio 画布没有 |
| `assist.tool_loop` | Y | **6.0** | 9.0 | 内核有了，未接聊天 |
| `post.pipeline` | Y | 6.0 | 7.0 | 无 ANR 超分可用；打码仍靠可选 ANR |
| `search.fts_works_prompt` | Y | 7.0 | 8.0 | 增量库有了；无 10k 真机、无 HTTP |
| `ingest.local_drop_nai_only` | Y | 7.0 | 8.0 | `/app` 图库页无拖入 |
| `gen.studio_frozen_txt2img` | Y | 7.0 | 8.0 | 付费闸门在；未做真机出图 |
| `publish.pixiv_browser` | Y | 7.0 | 8.0 | 用户 defer 账号验证 |
| `assist.split_desks` | Y | 7.0 | 8.0 | 分台是长板，不要合成单角色 |
| `restore.png_stealth_v4` | Y | 8.0 | 9.0 | 未知字段可回填；画布仍不读 mask |
| `start.one_click_launch` | Y | 8.0 | 9.0 | 云端无法真机验证 |
| `gen.cancel_balance_error` | Y | 8.0 | 9.0 | 缺 UI 取消 |
| `recover.generation_unknown` | Y | 8.0 | 9.0 | 崩溃 ≠ 没扣费 |
| `start.loopback_trust` | Y | 9.0 | 9.0 | 已是安全基线 |
| `search.visual_similar` | N | 5.0 | 7.0 | 库级，非 10k |
| `lineage.recipe_object` | N | 2.0 | 7.0 | 未做 |

**不要把 6.0 的 compile 说成 8.0 的画布完成。不要把合成 bench 说成 10k 成绩。**

---

## 9. 测试（Linux Cloud VM）

```
1132 passed, 68 skipped, 1 failed, 127 subtests
```

命令（PATH 上常常没有 `python`）：

```bash
python3 -m pip install -r requirements.core.lock.txt pytest langgraph langgraph-checkpoint-sqlite aiosqlite
python3 -m compileall -q -x "runtime|\.venv|node_modules|data" .
python3 -m pytest -q --ignore=tests/test_pixiv_selector_probe.py
python3 scripts/scan_sensitive.py --git-candidates --content-only
python3 scripts/bench_gallery.py --count 1000 --repeats 20
python3 scripts/check_windows_scripts.py
```

记录：

- 唯一失败：原有 `tests/test_product_quality_gate.py` P1=1。**不要删、不要降门槛。**
- `scripts/scan_sensitive.py --git-candidates --content-only`：clean
- `scripts/check_windows_scripts.py`：pass
- `scripts/bench_gallery.py --count 1000 --repeats 20`：hits=200，p95≈0.3ms，合成内存

Windows 全量：`scripts/verify.ps1` 或 `scripts/run_tests_windows.ps1`。诊断：`scripts/doctor_windows.ps1`。

---

## 10. 明确未做 / 不能假装完成

1. Studio img2img / inpaint **画布 UI**（`frontend/src/pages/StudioPage.tsx`）
2. tooling 接入 `planning.py` / 聊天
3. 图库 similar / dup / incremental 的 **HTTP 路由**
4. 虚拟相册 / 批量移动 preview-commit-restore（设计有，代码无）
5. v1.9 长期记忆 / TTS / 情感（且禁止窥屏）
6. `WIN-001`…`WIN-015` 真机：一键启动、打包、DPAPI、Defender、Live2D、大图库、junction
7. `WIN-012` 真实 NAI 出图
8. `WIN-013` Pixiv 登录/发布（用户 defer）
9. 合 `main`、发 Release、顶尖声明
10. 统一配方对象 `lineage.recipe_object`

---

## 11. 后续允许 / 禁止

### 允许（需用户明确下令）

- 在集成分支上做 Studio img2img 画布 UI（会碰 `frontend/`，先读现有 `StudioPage.tsx`，不要新开第二套生成客户端）
- 按 `GALLERY_INDEX_DESIGN.md` 加 **additive** HTTP 路由，且不改 `/api/ai_works_search` JSON
- Windows 真机跑 `PENDING_LOCAL_WINDOWS.md`
- 用户书面授权后做 **一次** 受控免费/限次 NAI（`WIN-012`）

### 禁止（即使用户说「继续升级」也不要自己做）

- 合 `main` / 发 Release / 改 LICENSE
- 连接 Manga / Phone
- 把 tooling 接入 `planning.py`（除非 Lead 书面过了 v1.6/v1.7 门槛）
- 做 v1.9 记忆 / TTS / 窥屏
- 使用或持久化任何聊天里的 Token
- 为了变绿而改 `test_product_quality_gate` 门槛
- 把 `scripts/bench_gallery.py` 写成 10k/100k 成绩
- 重做 Phase 0 审计
- 发明第二套 NAI 客户端、任务库、图库索引或权限系统

---

## 12. 给下一任的粘贴指令

```
执行模式继续为 CLOUD_WEB，除非本机已按 HANDOFF 切到 LOCAL_WINDOWS。
完整读取 docs/top-tier-upgrade/CLOUD_COMPLETE_REPORT.md 以及同目录
RUN_STATE.json、STATUS.md、OWNERSHIP.md、DECISIONS.md、CAPABILITY_MATRIX.md、
CLOUD_PRS.md、PENDING_LOCAL_WINDOWS.md、HANDOFF_CLOUD_TO_WINDOWS.md、NEXT_ACTION.md。
唯一仓库 h1neolzr7f/NaiXueZhang-Studio-Upgrade。
不要连接 Manga。不要重做 Phase 0。
checkout cursor/cloud-top-tier-integration-f036（报告写入 0c46e12；以分支 tip 为准）
云端可做的 v1.6 compile / v1.7 gallery_index / v1.8 kernel 已落地。
不要把 tooling 接入 planning.py。不要做 v1.9。
不要合并 main、不要发 Release、不要用真实 NAI Token。
下一步是 Windows WIN-001..015、Studio img2img 画布 UI、以及用户授权后的 WIN-012。
```

---

## 13. 关键代码入口

| 主题 | 文件 |
|---|---|
| NAI compile | `nai_char_modules/generation.py` |
| NAI HTTP | `nai/generate.py`、`nai_api.py` |
| PNG 回填 | `nai_char_modules/snapshots.py`、`nai_image_metadata.py` |
| 后处理 | `post_pipeline.py` |
| 图库索引 | `gallery_index.py`、`db.py` |
| 图库设计 | `docs/top-tier-upgrade/GALLERY_INDEX_DESIGN.md` |
| Tool kernel | `butler/tooling/` |
| 内核只读工具 | `butler/tooling/kernel_tools.py` |
| 计划器（未接 kernel） | `butler/planning.py` |
| Studio UI（无画布） | `frontend/src/pages/StudioPage.tsx` |

---

## 14. 回滚

- 本波：关闭 Draft PR #3，或 `git checkout main` @ `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`
- 不要 force-push `main`
- 图库新表可 `DROP TABLE gallery_index_files; DROP TABLE gallery_image_hashes;`
- 不要把 Worker 分支单独合进 `main`
