# Architecture Optimizer · Round 1

> Role: **A — Architecture Optimizer**  
> Baseline: Architecture Baseline v0 = `Acquire → Curate → Transform → Library` (D-019)  
> Repository: `h1neolzr7f/NaiXueZhang-Studio-Upgrade`  
> Branch tip researched: `cursor/cloud-top-tier-integration-f036` @ `11a7933`  
> Production code changed: **none**  
> Status: research only; not an implementation lease

本报告在 Baseline v0 上做定向优化，不从零重做总体架构。重大建议都给出证据等级、迁移风险、验证方法和 rollback。证据等级遵循任务书：E0 推测 / E1 代码 / E2 测试 / E3 实测 / E4 真实使用。

---

## 0. 方法与阅读范围

事实源按检查点报告顺序阅读：

- `docs/top-tier-upgrade/MULTI_MODEL_ARCHITECTURE_RESEARCH_BRIEF.md`
- `DECISIONS.md`（尤其 D-004、D-012…D-019）
- `STATUS.md`、`GATE_REVIEW.md`、`CLOUD_CHECKPOINT_REPORT.md`
- `CAPABILITY_MATRIX.md`、`GALLERY_INDEX_DESIGN.md`、`COMPETITOR_BASELINE.md`
- `ROADMAP.md`、`docs/UPGRADE.md`、`AGENTS.md`

生产代码与测试按四层抽样核对，而不是只读文档：

| 层 | 主要入口 | 关键测试 |
|---|---|---|
| Acquire | `crawler_hub.py`、`pixiv_nai_intake.py`、`crawler_qq.py`、`qq_gallery_ingest.py`、`routes/gallery.py` import-drop、`aitag_core/online.py` | `tests/test_pixiv_nai_crawler.py`、`tests/test_codex_import_drop.py`、`tests/test_crawler_storage_pipeline_fixes.py` |
| Curate / Library | `work_refs.py`、`db.py`、`db_queries.py`、`gallery_catalog.py`、`gallery_index.py`、`gallery_snapshot.py` | `tests/test_gallery_index.py`、`tests/test_gallery_index_http.py`、`tests/test_work_refs.py` |
| Transform | `nai_char.py`、`nai_char_modules/remix.py`、`nai_batch.py`、`generation_jobs.py`、`post_pipeline.py` | `tests/test_char_swap_http_contract.py`、`tests/test_generation_jobs.py`、`tests/test_post_pipeline.py` |
| Safety / failure | `nai/errors.py`、`nai/generate.py`、`local_secrets.py`、`server.py` | `tests/test_fault_injection.py`、`tests/test_p0_paid_security.py`、`tests/test_gallery_maintenance_migration_safety.py` |

结论原则：已有稳定路径默认 KEEP；只有代码/测试证据或可实验区分的收益才允许局部推翻。批量换角色是 Protected Strength，任何建议都必须通过其 regression gate。

---

## 1. Baseline v0 现状判断

D-019 把产品/数据边界写成四层。代码里这四层**已经存在为产品能力**，但**还不是统一运行时契约**。

```text
Acquire     Pixiv intake / QQ folder / local drop / Codex import / AITag online / generated scan
Curate      FTS + nai_tag_facets + favorites/queue + incremental hashes
Transform   remix recipe → GenerationJobManager → post_pipeline
Library     三套 SQLite 图库 + 文件系统 generated gallery
```

这是正确的产品切分，不应换成“一切皆图库”或“一切皆爬虫”。错误不在四层本身，而在层间缝合：

1. Acquire 适配器直接写 Library DB。
2. Remote / Cached / Materialized 没有一等状态，只有散落的 `downloaded` / `preview_downloaded` / receipts / HTTP cache。
3. Transform 产物落在独立的 `data/generated/`，与 Library 的 `WorkRef` 只有 sidecar 弱连接。
4. Curate 不能跨库，也不能把远程发现和本地资产放进同一次搜索。

这些是**边界遗漏**，不是总体架构选错。

---

## 2. 已经足够好、本轮明确 KEEP

下面这些设计已经有代码和测试锁，Optimizer 认为继续改会造成净损失。

### K1. 四层产品架构本身

D-019 把爬虫降为 Acquire Adapter，把 Library 定义为用户长期拥有的本地资产，而不是互联网镜像。这与现有三库隔离、AITag“只发现不入库”一致。

- Evidence: D-019；`aitag_core/online.py` 模块注释；`crawler_hub.py` 把 site/qq/pixiv 分成不同 target。
- Grade: **E1 + E2**（AITag / drop / Pixiv 各有测试）
- Verdict: **KEEP**。不要用单一图库或单一爬虫中心重写。

### K2. `WorkRef = {gallery_id, work_id}` 与搜索 JSON 冻结

D-004 / D-013 / D-015 冻结了公共接口。`WorkRef` 已经能区分三库和 `aitag-online` 选择集。页级身份用 `image_key("{work_id}:{page_index}")`，不要塞进 `WorkRef` 以免打favorites/queue。

- Evidence: `work_refs.py`；`tests/test_work_refs.py`；`tests/test_gallery_index_http.py` 锁 `/api/ai_works_search`。
- Grade: **E2**
- Verdict: **KEEP**。新能力只能 additive。

### K3. 三物理图库隔离 + NAI-only 准入

`site` / `codex` / `qqgroup` 分 DB、分 `images_dir`。drop 只接受 `codex`/`qqgroup`。`parse_nai_image` 拒 Comfy。这是产品身份，不是技术债。

- Evidence: `gallery_catalog.py`；`routes/gallery.py` `_DROP_GALLERIES`；`nai_image_metadata.py`；`tests/test_codex_import_drop.py`。
- Grade: **E2**
- Verdict: **KEEP**。禁止合并三库，禁止把索引变成 Comfy/SD 后门。

### K4. 批量换角色契约（Protected Strength）

必须原样保住的合同：

| 合同 | 位置 | 测试 |
|---|---|---|
| `/api/plugin/char-swap/*` 前缀与 passthrough | `routes/char_swap.py` | `tests/test_char_swap_http_contract.py` |
| `batch/preview` 本地预检，不打 NAI | `nai_char.batch_preview` | HTTP contract + `test_batch_preview_dedup.py` |
| `batch/run` 默认 `force_free=True` | `start_batch` | HTTP contract |
| 付费运行冻结 `patched_comment` | `nai_batch.start_batch` | generation job 测试 |
| 身份守卫：跨页无 match → `skipped` 不是 error | `transform()` | `tests/test_architecture_upgrade.py` |
| `billing_uncertain` / `unknown` 禁止自动重试 | `partition_retry_targets` | `tests/test_generation_jobs.py`、`test_fault_injection.py` |
| `BATCH_TARGET_MAX = 250` | `nai_char.py` | HTTP / batch 测试 |
| 深模块不得 import `nai_char` / `routes` | `nai_char_modules/*` | `tests/test_char_swap_module_architecture.py` |
| `compile_remix_recipe` 顺序：transform → style → sanitize → generation | `nai_char_modules/remix.py` | module contracts |

- Grade: **E2**
- Verdict: **KEEP**。任何 Acquire/Library 重构都必须把上述测试当 regression gate。禁止把换角色改造成通用 DAG。

### K5. 单一 NovelAI HTTP 客户端 + 付费语义

`nai_char.build_generate_payload` → `nai_api.generate_image` 是唯一 generate 客户端。5xx/超时后发送 = `billing_uncertain`，崩溃恢复 = `unknown` + `recovered_after_restart`。账本不猜 Anlas。

- Evidence: D-004 / D-012；`nai/generate.py`；`generation_jobs.py`；`tests/test_nai_generate_compile.py`。
- Grade: **E2**
- Verdict: **KEEP**。禁止第二客户端、禁止把 unknown 当没扣费。

### K6. Tool Kernel / LangGraph 分工

聊天只跑 read preview；付费/破坏性动作只产 `WorkflowRequest`。`planning.py` 零 import `butler.tooling`。

- Evidence: D-014 / D-017；`butler/tool_loop_bridge.py`；`tests/tooling/test_kernel_tools.py`。
- Grade: **E2**
- Verdict: **KEEP**。不要用插件运行时替换 LangGraph。

### K7. 增量索引 additive、embed 默认关闭

`gallery_index` 表在现有 per-gallery SQLite。`embed.provider=local_none`。`rebuild_fts` 是 repair。

- Evidence: D-013 / D-015；`gallery_index.py`；`tests/test_gallery_index.py`。
- Grade: **E2**（功能）/ **E0**（10k 性能）
- Verdict: **KEEP 设计**。性能声明保持 UNKNOWN。

### K8. 本机信任边界

默认 loopback、会话令牌 fail-closed、非 Windows 拒明文密钥、路径 jail、CORS 仅本机源。

- Evidence: `server.py`；`local_secrets.py`；`tests/test_p0_paid_security.py`。
- Grade: **E2**（Linux 合同）/ **E0**（Windows DPAPI 真机，WIN-015）
- Verdict: **KEEP**。安全基线不能为远程联合搜索让路。

### K9. AITag 作为远程发现、不是第二图库

`AitagClient` 只缓存 HTTPS JSON，下载/持久化留给显式调用方。`aitag-online` 在 `SELECTION_ONLY_GALLERY_IDS`。

- Evidence: `aitag_core/online.py`；`aitag_core/storage/http_cache.py`；`work_refs.py`。
- Grade: **E1 + E2**
- Verdict: **KEEP 产品语义**。这是 RemoteAssetRef 的现成原型，不要把它“升级”成自动入库。

### K10. 分台与 TTS 拆分

小祥/凑企鹅分台是长板。TTS 不进木桶。禁止窥屏/钩子/God Agent。

- Evidence: D-018；`CAPABILITY_MATRIX.md`。
- Grade: **E2**
- Verdict: **KEEP**。

---

## 3. 真正值得改的问题

按“错误抽象 / 遗漏边界 / 耦合 / 未来瓶颈 / 可简化”分类。每条都写清**不要改成什么**。

### P1. Acquire 没有统一写出边界（错误抽象 + 耦合）

**现象。** Pixiv、QQ、drop、Codex 都直接写 Library：

| 路径 | 写出函数 | DB |
|---|---|---|
| Pixiv | `PixivNAIIntake._persist` 内嵌 SQL | `data/aitag.db` |
| QQ / drop / Codex | `upsert_local_work` → `_upsert_full` | 各 gallery.db |
| Legacy site crawler | `upsert_list_items_batch` / `save_detail` | `aitag.db`（产品路径已禁用） |

D-019 要求 “Provider 不直接写 Library DB”。今天全部违反。Pixiv 与 `upsert_local_work` 的 provenance 字段也不对称：Pixiv 写 `works.source_url` + `work_images.source_sha256`；QQ/drop 主要把 `source` 塞进 `list_json`。

**这不是要求立刻重写四个管道。** 正确修正是加一层 **LibraryWriter / Materializer**，现有管道改成调用它，而不是发明新爬虫框架。

- Evidence: `pixiv_nai_intake.py` `_persist`；`scripts/gallery_import_common.py` `upsert_local_work`；D-019。 **E1**
- User value: 高。新 Provider 否则会继续复制 SQL。
- Migration risk: 中。若一次改 Pixiv SQL，intake dirty-flag / orphan reconcile 容易回归。
- Proposed change: **MODIFY**。先写契约测试：Provider 不得 `Database.conn.execute` 进 `works`/`work_images`。第一波只让 QQ/drop/Codex 走同一 writer；Pixiv 第二波。
- Validation: 见 `candidate-v1.md` V-ACQUIRE-WRITER。
- Rollback: writer 变 facade，内部仍调现有 upsert。
- What not to do: 不要引入消息队列、不要把 intake 改成微服务、不要 GPL 引入 gallery-dl。

### P2. Remote / Cached / Materialized 只有散落旗标（遗漏边界）

**现象。** 实际状态存在，但没有名字：

| 真实状态 | 今天怎么表示 |
|---|---|
| 远程元数据 | AITag JSON cache；legacy `list_json` 且 `detail_json` 空 |
| 远程收藏引用 | `favorites.json` 可含 `aitag-online` WorkRef，文件不在本地 |
| 已物化页 | `work_images.downloaded=1` + `local_path` |
| 预览物化 | `preview_downloaded=1` |
| 失败/拒绝页 | `pixiv_nai_receipts` / `qq_ingest_files` |
| HTTP 缓存 | `DiskResponseCache`（AITag only） |

任务书要验证的三态**没有类型**。收藏“引用 vs 快照”也没有显式策略：favorites 存的是 WorkRef，不是字节快照。远程失效时收藏仍指向死引用。

- Evidence: `work_images` schema；`favorites.py`；`aitag_core/storage/http_cache.py`。 **E1**
- 是否需要新列： **UNKNOWN**。现有旗标可能够用，先做映射原型再决定。
- Proposed change: **ADD 只读投影** `asset_lifecycle(work_ref, page) -> remote_ref | cached | materialized | partial | removed`。第一波不改 schema。
- Validation: V-LIFECYCLE-MAP。
- Rollback: 删除投影函数。
- What not to do: 不要为三态新建第二套资产表。

### P3. Provenance / 换角色血缘不闭合（遗漏边界，高价值）

**现象。** Pixiv 物化时有 provider URL / remote id / sha256。QQ/drop 弱。生成图 sidecar 有：

- `work_id`、`source_gallery_id`、`generation_series_id`
- `prompt_snapshot`
- `pipeline_steps`

没有：

- 配方版本 / recipe fingerprint
- 父生成图（img2img 链）
- 命中的 identity / 替换槽
- license / rights（即使 Pixiv 也只有 `x_restrict` → rating）

`lineage.recipe_object` 在能力矩阵是 2.0。ROADMAP 也把 Recipe 列为未做。批量换角色的可复现性目前靠冻结 comment + 任务 id，足够跑生产，不够做“派生关系查询”。

- Evidence: `generated_gallery.register_generated`；`CAPABILITY_MATRIX` `lineage.recipe_object=2.0`；`ROADMAP.md`。 **E1**
- User value: 高，且直接服务 Protected Strength。
- Migration risk: 低（additive sidecar 字段）。
- Proposed change: **ADD** 到 `.meta.json`：`parent_generated_stem`、`recipe_fingerprint`、`transform_summary`。不建 DAG 引擎。
- Validation: V-LINEAGE-META。
- Rollback: 读取时缺字段当旧图。
- What not to do: 不要把 generated 合并进三库 SQLite；不要上 C2PA 签名基础设施。

### P4. 缓存是多套 TTL，不是 Cache Manager（重复基础设施）

存在至少：`gallery_cache`（进程 TTL）、`cached_scope_total`、`generated_gallery` 扫描缓存、`DiskResponseCache`、token 5s TTL、director LRU、audit JSON。`gallery_cache` 的 `work_lite:{gid}:{id}` TTL 180s，**写路径不失效**。

这还没到“必须造 Cache Manager”的程度。真正的缺陷是 **mutation 不失效** 和 **AITag 磁盘缓存与图库缓存语义不同却同名“cache”**。

- Evidence: `gallery_cache.py`；`routes/gallery.py` work_lite；`routes/settings.py` 只清 `api_config`。 **E1**
- Proposed change: **MODIFY**。在 drop/merge/upsert/remove 后 `invalidate(f"work_lite:{gid}:{id}")`。给 `DiskResponseCache` 保持独立，不要合并。
- Validation: V-CACHE-INVALIDATE。
- Rollback: 恢复 TTL-only。
- What not to do: 不要 Redis、不要统一缓存总线、不要跨进程共享。

### P5. 备份/回滚只覆盖 site 库（遗漏边界）

`GallerySnapshotManager` 针对 `data/aitag.db` + `data/images`。Codex/QQ 没有对等 snapshot。WebP migrate 有单行 rollback，测过 DB lock。HTTP 只有 create snapshot，没有 restore 路由。

用户旧图库迁移/rollback 是任务书硬要求。今天对自选库/Q群不成立。

- Evidence: `gallery_snapshot.py`；`gallery_maintenance.py`；`tests/test_gallery_snapshot.py`。 **E1 + E2**（site）/ **E0**（codex/qq）
- Proposed change: **ADD** 复用现有 manager，参数化 `db_path` + `images_dir`。restore 保持 CLI/`confirm=True`，不要急着做 HTTP。
- Validation: V-GALLERY-SNAPSHOT-ALL。
- Rollback: 新入口不调用即可。
- What not to do: 不要用 zip snapshot 代替 folder-merge journal（设计文档 §9 已说明粒度错误）。

### P6. 虚拟相册与移动 journal 仍是设计（已知缺口，不要提前工程化）

`GALLERY_INDEX_DESIGN.md` Phase D/E 已设计 preview/commit/restore 与 albums。生产里 folder merge 仍立即写 `list_json`。favorites/queue 是最接近的虚拟集合，但不可查询、无 smart rule。

- Evidence: 设计文档 §8–9；`routes/gallery.py` merge。 **E1**
- Proposed change: **LATER / 有条件 ADD**。先落地 P5 备份，再做 journal。不要和 Provider 边界同一波。
- Validation: 设计文档已有单测方案。
- What not to do: 不要双路径 merge。

### P7. 后处理仍是可选 ANR 短板，但不是架构错误

`post.pipeline=6.0`：无 ANR 时 `mosaic:unavailable`，Lanczos 继续。这是能力缺口，不是四层架构问题。不要为了打码引入插件沙箱或第二流水线框架。

- Evidence: D-010；`tests/test_post_pipeline.py`。 **E2**
- Verdict: **KEEP 降级语义**。替代打码方案属于实现波，不是本轮架构必选项。

### P8. 可观测性在付费路径强、在 Acquire/Library 弱

付费失败分类已经是产品长板。`tests/test_fault_injection.py` 名字大于内容：只锁 taxonomy，不做真实注入。`usage_ledger.record_usage` 吞掉 SQLite 错误。`generation_jobs.json` 损坏恢复已实现、缺少测试。

- Evidence: `usage_ledger.py`；`generation_jobs._restore_locked`；`tests/test_fault_injection.py`。 **E1**
- Proposed change: **MODIFY** 小补强，不要上 OpenTelemetry。
- What not to do: 不要统一“可观测性平台”。

### P9. 性能与 Windows 真机是 UNKNOWN，不是设计失败

`scripts/bench_gallery.py` 是内存微基准。WIN-010/012/015 仍 queued/blocked。架构上 FTS 两段查询、`skip_total`、增量 dirty-set 是正确形状。缺的是测量，不是新引擎。

- Evidence: `BENCHMARKS.md`；`scripts/bench_gallery.py` 自身注释。 **E1**
- Verdict: **KEEP 查询形状**。10k/100k/1M 全部 **UNKNOWN**，用 V-PERF-WINDOWS 补。

### P10. 可以简化的地方

1. Legacy `crawler.py` + `crawler_task.PRESETS` 仍在树内，产品路径已禁用。保留代码可以，但 watchdog 仍读 legacy `preview_downloaded` 指标，和 Pixiv 心跳不一致。  
   - 建议：watchdog 指标切到 Pixiv heartbeat；legacy 标 `SUPERSEDED`，不删（回滚与考古）。 **E1**
2. `prompt_fts` 与 `prompt_work_fts` 双表由 `crawl_state.prompt_work_fts_ready` 切换。这是迁移桥，不是永久设计。修好后可只留 work 级。先测再删。 **E1**，删表风险中。
3. 不要把 `RemixRecipe`（`aitag_core/recipe.py`）和 `compile_remix_recipe` 合成一个运行时。前者服务在线发现，后者服务本地换角色。保持 Adapter，避免循环。 **E1**

---

## 4. 横向能力逐项判断（Optimizer 视角）

任务书 §3 的 15 项，这里只判断“要不要新造系统”。分数与机制细节见 Barrel 报告。

| # | 能力 | Optimizer 判断 | 理由 |
|---|---|---|---|
| 1 | Canonical Asset Model | **薄类型，不换存储** | `WorkRef` + `image_key` 已够；缺的是远程引用类型 |
| 2 | Remote vs Local lifecycle | **只读投影，先不改 schema** | 旗标已存在；三态是命名问题 |
| 3 | Tag / Alias / multilingual | **KEEP 现有 facets；别名 LATER** | `nai_tag_facets` 已有 character/copyright/artist；Hydrus sibling 过重 |
| 4 | Provider capability negotiation | **薄描述符** | Pixiv 已有 delay/retry/quarantine；不要通用协商协议 |
| 5 | Multi-provider Ranking | **REJECT 本轮** | 用户价值低；会污染 NAI-only 身份 |
| 6 | Cache Manager | **REJECT 统一管理器；MODIFY 失效** | 见 P4 |
| 7 | Provenance / lineage | **ADD sidecar 字段** | 见 P3；服务换角色 |
| 8 | Transform Pipeline / Recipe | **KEEP 顺序编译器** | DAG 无需求证据 |
| 9 | Plugin isolation | **KEEP 模块边界，REJECT 沙箱** | char-swap 是同进程插件；沙箱会破坏换角色 |
| 10 | Schema migration / backup | **ADD 复用 snapshot 到三库** | 见 P5 |
| 11 | Observability | **MODIFY 付费/ledger 小洞** | 见 P8 |
| 12 | 10k/100k/1M | **UNKNOWN，先测** | 见 P9 |
| 13 | Provider 降级 | **KEEP 付费路径；Acquire 已隔离** | 远程挂不影响本地三库，已是事实 |
| 14 | Local + Remote 联合搜索 | **有条件，后置** | 先要 RemoteAssetRef 投影；联合搜索会碰到 loopback/CORS |
| 15 | 现有功能兼容 | **最高优先级 KEEP** | 搜索 JSON、换角色 HTTP、NAI 客户端冻结 |

---

## 5. 建议的最小架构增量（仍不实施）

若后续实现，顺序必须保护换角色和旧库：

```text
Wave A  只读：lifecycle 投影 + 换角色 lineage sidecar 契约测试
Wave B  LibraryWriter facade（先 QQ/drop/Codex，后 Pixiv）
Wave C  三库 snapshot 复用
Wave D  work_lite 失效 + ledger 失败可见
Wave E  设计已有的 move journal / albums（独立 lease）
```

任何一波失败都只回滚该波。禁止 Big Bang。

---

## 6. 明确拒绝的“优化”

| 诱惑 | 为什么拒绝 | Grade |
|---|---|---|
| 合并三库到一个 SQLite | 打破 WorkRef、路径 jail、drop 合同 | E1 |
| Hydrus 式 hash 主身份替换 work_id | Pixiv/QQ id 是用户心智与 URL；hash 已是辅键 | E1 |
| ComfyUI / 通用 DAG | 换角色是顺序 recipe；DAG 无用户故事 | E0 |
| 第二任务库给索引或换角色 | D-013 / AGENTS.md 禁止 | E1 |
| 聊天 Tool Loop 直接 generate | D-004 / D-017 | E2 |
| 默认 embedding / 出网上传 | D-G3 精神；`local_none` | E1 |
| 抄 AGPL/GPL 进 MIT 树 | AGENTS.md；COMPETITOR_BASELINE | E1 |
| 为远程浏览自动永久下载 | D-019 | E1 |
| 微服务 / 分布式队列 | 单机 Windows 产品 | E0 |

---

## 7. 本报告的 UNKNOWN（不收敛）

1. 现有旗标映射三态是否足够，还是必须加列。  
2. Pixiv `_persist` 迁到 LibraryWriter 会不会破坏 dirty-flag / quota / thumbnail-only。  
3. 10k 图库下 incremental + similar 的真实 p95。  
4. 远程收藏失效时，用户要“死链提示”还是“上次快照”。无 E4。  
5. `recipe_fingerprint` 用冻结 comment 的 canonical JSON 是否稳定（键序、浮点、未知字段）。  
6. Codex/QQ snapshot 体积是否可接受（原图 + WebP）。  
7. 双 FTS 表能否在不修 repair 路径的情况下删除 `prompt_fts`。

这些必须靠 prototype / bench / 反例测试，而不是再开一轮从零设计。

---

## 8. Rollback 总则

本轮零生产改动。若未来按本报告实施：

- 文档建议可整体丢弃，不影响 `main`。
- 运行时改动必须 feature-flag 或 additive schema。
- 换角色回归：`tests/test_char_swap_*.py`、`tests/test_generation_jobs.py`、`tests/test_nai_generate_compile.py` 全绿。
- 图库回归：`tests/test_gallery_index*.py`、`tests/test_codex_import_drop.py`、搜索 JSON freeze。
- 用户数据：禁止改 `PRAGMA user_version` 向下；snapshot 先于 migrate。
