# Architecture Candidate v1

> Status: **Candidate**（未冻结，未实施）  
> Inputs: Architecture Optimizer Round 1 + Barrel Benchmark Researcher Round 1  
> Baseline: v0 = `Acquire → Curate → Transform → Library`（D-019）  
> Production code changed: **none**  
> Next required role: Adversarial Reviewer（见 `ROUND_1_HANDOFF.md`）

本文件综合 A/B，给出可攻击的候选，而不是假装已经收敛。架构级修改不靠纯 E0。证据不足的项只进入验证方案，不进入实现清单。

决策动词：

- **KEEP** — 维持现状，Reviewer 也应保护
- **MODIFY** — 在现有对象上改，不换总体形状
- **ADD** — 添加剂（类型、字段、测试、复用现有组件的新入口）
- **REJECT** — 本轮及可预见的下一实现波都不做
- **UNKNOWN** — 缺 E2/E3，先做 benchmark / test / prototype

---

## 0. Candidate 一句话

保住批量换角色和三库/付费/NAI-only 长板；用**薄 RemoteAssetRef + LibraryWriter facade + generated lineage 字段 + 三库 snapshot 复用**补 D-019 的缝；不引入 DAG、统一缓存平台、联合搜索引擎或 hash 主身份。

总体架构：**KEEP Baseline v0**。Candidate v1 是边界补强，不是 v0 的替代品。

---

## 1. 决策表

| ID | 主题 | 决策 | 证据 | 来源 | 实现波 |
|---|---|---|---|---|---|
| D1 | 四层产品架构 | **KEEP** | E1+E2 | A K1, D-019 | — |
| D2 | `WorkRef` / 搜索 JSON / 单一 NAI 客户端 | **KEEP** | E2 | A K2/K5, D-004 | — |
| D3 | 三库隔离 + NAI-only | **KEEP** | E2 | A K3 | — |
| D4 | 批量换角色全部现有合同 | **KEEP** | E2 | A K4, B C8 | — |
| D5 | Tool Kernel / LangGraph / planning 隔离 | **KEEP** | E2 | A K6 | — |
| D6 | 增量索引 additive + `local_none` embed | **KEEP** | E2 | A K7 | — |
| D7 | loopback / 令牌 / 路径 jail | **KEEP** | E2 | A K8 | — |
| D8 | AITag 只发现不自动入库 | **KEEP** | E1+E2 | A K9 | — |
| D9 | 分台；TTS 不进木桶 | **KEEP** | E2 | A K10 | — |
| D10 | `compile_remix_recipe` 顺序编译，不上 DAG | **KEEP** | E2 | A K4, B 2.5 | — |
| D11 | 付费 taxonomy / 不自动重试 5xx/unknown | **KEEP** | E2 | A K5, B C11 | — |
| D12 | `DiskResponseCache` 独立存在 | **KEEP** | E1 | B 2.4 | — |
| D13 | `post.pipeline` 无 ANR 降级语义 | **KEEP** | E2 | A P7, D-010 | 打码替代属实现，非架构 |
| D14 | RemoteAssetRef 类型（不换存储） | **ADD** | E1 | A P2, B 2.1 | Wave A |
| D15 | lifecycle 只读投影 | **ADD** | E1 | A P2 | Wave A |
| D16 | generated lineage 三字段 | **ADD** | E1 | A P3, B 2.2 | Wave A |
| D17 | `recipe_fingerprint` 纯函数 | **ADD** | E1 | B B9 | Wave A |
| D18 | `upsert_local_work` 补 sha256/url | **MODIFY** | E1 | A P1/P3, B B3 | Wave B |
| D19 | LibraryWriter facade，先 QQ/drop/Codex | **MODIFY** | E1 | A P1, B B4 | Wave B |
| D20 | Pixiv `_persist` 迁入 writer | **UNKNOWN** | E1 现状 / E0 迁移安全 | A §7.2 | 先 prototype |
| D21 | `work_lite` 写失效 | **MODIFY** | E1 | A P4, B B6 | Wave D |
| D22 | 统一 Cache Manager / Redis | **REJECT** | E0 收益不足 | A P4, B C6 | — |
| D23 | snapshot 复用到 codex/qq | **ADD** | E1+E2(site) | A P5, B 2.7 | Wave C |
| D24 | HTTP snapshot restore | **REJECT** 本轮 | E1 | A P5 | 保持 CLI + confirm |
| D25 | move journal / virtual albums | **UNKNOWN**→有设计 | E1 设计 / E0 需求频率 | A P6 | 独立 lease，不进 v1 必做 |
| D26 | ledger 失败可见 + corrupt jobs 测试 | **MODIFY** | E1 | A P8, B B7 | Wave D |
| D27 | OpenTelemetry / 统一日志平台 | **REJECT** | E0 | A P8 | — |
| D28 | 10k/100k 性能结论 | **UNKNOWN** | E0 测量 | A P9, B C12 | V-PERF |
| D29 | 为 1M 换引擎 | **REJECT** | E0 错误目标 | B 2.8 | — |
| D30 | Local+Remote 联合搜索实现 | **REJECT** 本轮 | E1 缺失 + 安全耦合 | B 2.9 | 先 D14 |
| D31 | Multi-provider Ranking | **REJECT** | E1 低价值 | B C5 | — |
| D32 | Hydrus hash 主身份 | **REJECT** | E1 | A §6, B 2.1 | — |
| D33 | 合并三库 / 合并 generated 进 SQLite | **REJECT** | E1 | A §6 | — |
| D34 | 插件进程沙箱 | **REJECT** | E1 会伤换角色 | B 2.10 | — |
| D35 | 抄 AGPL/GPL / 第二 NAI 客户端 / 第二任务库 | **REJECT** | E1 硬边界 | AGENTS / D-004 | — |
| D36 | Hydrus/Danbooru 别名层 | **REJECT** 本轮 | E0 无痛点测量 | B 2.6 | LATER |
| D37 | C2PA / Comfy lineage | **REJECT** | E1 冲突 NAI gate | B 2.2 | — |
| D38 | 自动物化远程浏览 | **REJECT** | E1 D-019 | A K9 | — |
| D39 | 删除 legacy `crawler.py` | **REJECT** 本轮 | E1 考古/回滚 | A P10 | 只改 watchdog 指标则 MODIFY 另议 |
| D40 | 双 FTS 表删 `prompt_fts` | **UNKNOWN** | E1 | A P10 | V-FTS-DUAL |
| D41 | Provider 薄描述符（文档+测试） | **ADD** | E1 | B 2.3 | Wave B |
| D42 | 远程收藏死链策略 | **UNKNOWN** | E0 无 E4 | A §7.4 | V-FAV-DEAD |
| D43 | Windows DPAPI/一键/大库 | **UNKNOWN** | 已记录 WIN-* | PENDING_LOCAL_WINDOWS | 本地接管，非本候选实现 |

---

## 2. Candidate v1 目标形状（逻辑，非新代码）

```text
                    ┌─ RemoteAssetRef (AITag / 未来源)
Online discovery ───┤      不写 Library
                    └─ HTTP DiskResponseCache

Explicit user action: Add to My Library / import-drop / Pixiv intake / QQ ingest
                              │
                              ▼
                     LibraryWriter (facade)
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
           site DB         codex DB         qq DB
           + images        + images         + images
              │
              ▼
           Curate (FTS / facets / hashes / favorites)
              │
              ▼
           Transform (compile_remix_recipe → GenerationJobManager)
              │
              ▼
           generated/ + sidecar lineage (parent, fingerprint, summary)
              │
              ▼
           optional post_pipeline → 仍回 generated，不改三库 PK
```

Provider 细节停在 Adapter。Library/Processor 只认 `WorkRef` / `RemoteAssetRef` / writer 记录。

---

## 3. Feature Preservation Matrix

| 功能 | Candidate 是否触碰 | 必须保持的合同 | Gate |
|---|---|---|---|
| 批量换角色 preview/run/retry | 仅可能读 sidecar 新字段 | HTTP 形状、force_free、冻结 comment、身份 skip、250 上限、409 needs_review | `tests/test_char_swap_*.py`、`test_generation_jobs.py` |
| Studio txt2img/img2img/inpaint | 不触碰 | 单一客户端、mask align、lone image 不擅自 img2img | `test_nai_generate_compile.py`、`test_studio_canvas.py` |
| `/api/ai_works_search` | 不触碰 JSON | page/items/total/gallery_id | `test_gallery_index_http.py` |
| 三库 drop / NAI gate | writer 内部仍走 parse | 非 NAI 拒绝；site 拒 drop | `test_codex_import_drop.py` |
| Pixiv intake | Wave B 不动 SQL | dirty-flag、orphan、quota、receipts | `test_crawler_storage_pipeline_fixes.py` |
| Favorites / queue | RemoteAssetRef 只扩展选择集语义 | schema v2 `WorkRef` | `test_work_refs.py` |
| Companion / kernel | 不触碰 | planning 零 import tooling | `test_kernel_tools.py`、`test_companion_v19.py` |
| 付费确认 | 不触碰 | WorkflowRequest；5xx 不重试 | `test_p0_paid_security.py` |
| 旧用户 `data/` | snapshot 先于任何 migrate | 不降 `user_version` | `docs/UPGRADE.md` |

目标保留率：**100% 现有稳定功能**。Candidate 若做不到，该项降为 REJECT 或 UNKNOWN。

---

## 4. 验证方案（证据不足就做这些，不写生产代码）

### V-ACQUIRE-WRITER（服务 D19 / D20）

**问题：** LibraryWriter 是减分叉还是空包装？Pixiv 迁移是否扩大崩溃窗口？

**Prototype（临时目录，不进生产）：**

1. 把 `upsert_local_work` 抽成可注入的 `persist_local_work(...)` 接口，Pixiv `_persist` 先**不改**，用适配器记录“若走 writer 会写入的字段集合”。
2. 对比字段：`source_url`、`source_sha256`、`list_json.source`、`crawled_at`、多页。
3. 用现有 `tests/test_codex_import_drop.py` 夹具跑 facade。
4. Pixiv：只做纸面 diff + 针对 `_mark_intake_dirty` / `_reconcile_if_dirty` 的序列图，不在 prototype 里重写 SQL。

**Accept：** QQ/drop/Codex 字段超集对齐 Pixiv 的 provenance 最小集，且零测试红。  
**Reject writer：** 若 facade 需要复制 Pixiv 事务细节才能正确，则保持分叉，只做 D18 字段补齐。

**目标证据：** E2（QQ/drop）+ E1 设计（Pixiv）。E3 等有人用真实 Pixiv 任务干跑。

### V-LIFECYCLE-MAP（服务 D14 / D15 / D42）

**问题：** 现有旗标能否表达三态？

**Prototype：** 纯函数 `classify_asset(row) -> lifecycle`，输入来自：

- 已下载 `work_images` 行
- `downloaded=0` 但有 `source_url`
- `aitag-online` favorite
- `pixiv_nai_receipts` rejected
- `removed_status` 各值
- generated 文件 + 无三库行

**Test：** 每类至少 1 个夹具。不允许为了让函数好看而改 DB。

**Accept：** 全部现有行能分类，无“必须加列”的反例。  
**Add-column：** 仅当出现无法表达的“远程收藏且本地有过期缓存字节”之类。当前这是假设，标 E0。

### V-LINEAGE-META（服务 D16 / D17）

**问题：** fingerprint 是否稳定？旧 sidecar 是否仍能分组？

**Test（可先写在 tests/，本轮不写）：**

1. 同一 recipe 两次 canonical JSON → 同一 sha256。
2. 仅未知厂商键不同 → 指纹不变（未知键不进指纹）。
3. 缺新字段的旧 `.meta.json` → `_group_key` 与现在一致。
4. 设 `parent_generated_stem` 不改变现有 group API 形状。

**反例：** 指纹吃进 `seed=-1` 的运行时解析，导致同一次点击两次预览指纹不同。必须锁。

**目标证据：** E2。付费真机复现链仍是 E0，直到 WIN-012。

### V-CACHE-INVALIDATE（服务 D21）

**Test：** 打开 work_lite 缓存 → 改 title/merge → 立即再读 lite ≠ 旧 title。TTL 未过也必须新。  
**反例：** 只 invalidate 当前 gallery，漏掉 generated source cache（300s）导致侧栏旧标题。若出现，扩大 invalidate 集合或标 UNKNOWN。

### V-GALLERY-SNAPSHOT-ALL（服务 D23）

**Prototype：** 临时 Codex 库 20 张 WebP + `gallery.db` → create → verify → restore(confirm=True) → integrity_check。  
**反例：** restore 误停 Pixiv crawler 或锁 site `aitag.db`。必须按 gallery 作用域加锁。  
**云端限制：** 只能小夹具。真实体积 E3 留 Windows。

### V-LEDGER-JOBS（服务 D26）

**Test：**

1. mock `record_usage` 抛 `sqlite3.Error` → job item 带 `usage_record_failed=true`，生成仍成功，且**不**触发重试。
2. 把 `generation_jobs.json` 写成非法 JSON → `restore_blocked`，新付费 job 拒绝，预览/免费路径策略保持现状并写明。

现有 `test_fault_injection.py` 应改名或补真实注入；本候选只要求补测试，不改 taxonomy。

### V-PERF-WINDOWS（服务 D28）

**不能在 Cloud VM 上宣称。** 方案：

| 步骤 | 数据 | 指标 | 非目标 |
|---|---|---|---|
| 1 | 合成 1k NAI PNG（可重复 seed） | import 墙钟、incremental-100、keyword p95、similar p95 | 不是用户库 |
| 2 | 若有真实库：10k | 同上 + 缩略图滚动 RSS | 禁止把 step1 写成 10k |
| 3 | 100k 仅当 step2 p95 有预算 | 决定是否分桶 similar | 1M 不做 |

记录 OS/CPU/RAM/SSD。失败 bench 不得删除。`scripts/bench_gallery.py` 继续只当 parser 微基准。

**目标证据：** E3。未跑之前 C12 保持 UNKNOWN。

### V-FTS-DUAL（服务 D40）

**Prototype：** 在夹具库比较 `prompt_fts` vs `prompt_work_fts` 的 search_works 结果集。  
**Accept 删除：** 结果集相等且 repair 只走 work 表。  
**Keep both：** 任一查询依赖 page 级 prompt 行。

### V-FAV-DEAD（服务 D42）

**Prototype：** favorite 指向不存在的 AITag id / 已 removed 的 site work。UI/API 应返回 `missing` / `source_gone`，不得抛 500，不得自动下载。  
**策略选择（需 Reviewer + 产品，不是架构独断）：** 死链提示 vs 过期快照。无 E4 前不选快照（快照会变成静默镜像）。

### V-SIMILAR-BUCKET（服务 D28 附属）

读 `gallery_index.find_similar`：若是全表 Hamming，10k 可能 O(n)。用 1k 夹具测 Python 循环时间，外推 10k/100k，**外推标 E0**，只决定要不要先写分桶 prototype。

### V-CHAR-SWAP-REGRESSION（所有实现波的门）

任何代码波开始前重跑：

```text
python3 -m pytest -q \
  tests/test_char_swap_http_contract.py \
  tests/test_char_swap_module_architecture.py \
  tests/test_char_swap_reliability.py \
  tests/test_batch_preview_dedup.py \
  tests/test_generation_jobs.py \
  tests/test_nai_generate_compile.py \
  tests/test_gallery_index_http.py \
  tests/test_p0_paid_security.py
```

少一项都不能声称“没伤换角色”。

---

## 5. 失败场景对照（任务书 §8）

| 场景 | Candidate 态度 | 现有证据 | 还需 |
|---|---|---|---|
| Provider 429/5xx/timeout | KEEP 现有分层重试 | E2 | 真 HTTP 注入仍弱 |
| API/schema/CORS 变 | KEEP CORS；Provider 描述符只文档化 | E2 CORS | 源站 schema 变属 E0 |
| 网络中断 | 本地三库应仍可搜 | E1 隔离 | 缺断网集成测 |
| cache 爆满 | AITag cache 有 max_bytes | E1 | `gallery_cache` 无上限，标 UNKNOWN 是否要 cap |
| disk full | quota / GalleryStorageQuotaExceeded | E2 部分 | 生成中途 disk full E0 |
| SQLite lock/corruption | WAL + busy_timeout；jobs JSON 隔离 | E2 migrate lock | 主库 corrupt 恢复 E0 |
| 部分成功写入 | Pixiv dirty-flag + orphan | E2 | writer 不得取消该窗口 |
| migration 中断 | WebP 单行 rollback | E2 | 跨行无全局回滚，KEEP 并写明 |
| 旧版本回退 | snapshot | E2 site only | V-GALLERY-SNAPSHOT-ALL |
| NAI 已扣费结果未知 | KEEP unknown | E2 | WIN-012 |
| 批量换角色部分失败 | KEEP 分项 ok/fail/skip | E2 | lineage 不得改变该语义 |
| Transform crash | job unknown | E2 | — |
| plugin/provider 越权 | kernel 不执行付费；路径 jail | E2 | 沙箱 REJECT |
| 100k+ 性能 | UNKNOWN | — | V-PERF |
| Remote 收藏失效 | UNKNOWN | — | V-FAV-DEAD |
| provenance 缺失 | ADD 字段 | E1 | V-LINEAGE-META |

不要为覆盖本表一次性建设复杂基础设施。

---

## 6. 建议实现顺序（若 Reviewer 放行）

必须满足：不改生产直到 Reviewer 轮次结束；即使之后实施，也按波提交。

1. **Wave A（最低风险）** D14–D17 类型/投影/sidecar 契约与测试。零用户可见行为变化也可接受。  
2. **Wave B** D18 + D19 + D41。不动 Pixiv SQL。  
3. **Wave C** D23 三库 snapshot。  
4. **Wave D** D21 + D26。  
5. **测量门** V-PERF / WIN-* 。没有 E3 不得提高 C12 分数。  
6. **独立 lease** D25 albums/journal。  
7. **仅当 V-ACQUIRE-WRITER 接受** 才讨论 D20 Pixiv。

Rollback boundary：每波独立 revert。用户 `data/` 在 C 波前先 snapshot。

---

## 7. 能力记分牌（候选后，诚实）

| 桶 | 现在 | 若只完成 Wave A–D（仍无 Windows 大库） | 不要宣称 |
|---|---:|---:|---|
| C1 Asset model | 6.5 | 7.0 | 统一资产平台 |
| C2 Lifecycle | 5.5 | 6.5 | 完整三态产品 |
| C7 Lineage | 4.5 | 6.5 | 配方系统 / C2PA |
| C4 Provider | 5.0 | 6.0 | 通用 Provider 框架 |
| C6 Cache | 5.5 | 6.5 | Cache Manager |
| C10 Backup | 6.0 | 7.5 | 跨机同步 |
| C12 Perf | 2.0* | 2.0* | 任何 10k 成绩 |
| C15 Compat | 8.5 | 8.5 | — |
| 换角色 Protected | 8.0 量级合同 | 必须仍 ≥ 现在 | “重构后更现代” |

核心产品木桶（`post.pipeline` 6.0 等）**本候选不声称提高**。那是实现/ANR/Windows 问题，不是 v1 架构必做。

---

## 8. 对 Integrator 的预告（本轮不启用）

若干轮后若启用 Judge，必须看到：

- 本文件决策表未被 Reviewer 打穿的子集
- V-* 的实际测试/prototype 输出（至少 E2）
- 被拒方案清单（本节 D22/D27/D29–D38 等）
- Feature Preservation Matrix 全绿

在那之前，**不要把 Candidate v1 当成 Baseline v1**。Baseline 升级只发生在 Review + 验证之后。
