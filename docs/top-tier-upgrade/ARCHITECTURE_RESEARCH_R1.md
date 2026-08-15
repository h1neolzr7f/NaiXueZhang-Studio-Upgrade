# 多模型架构研究 · 第 1 轮独立深度研究报告

> Role: Architecture Optimizer(兼建 Capability 证据基线,供 B/C 后续使用)
> Method: `MULTI_MODEL_ARCHITECTURE_RESEARCH_BRIEF.md` 定义的 Baseline v0 + 木桶标杆法 + Protected Strengths + 证据等级 + Freeze Gate
> Baseline: Architecture Baseline v0(`Acquire → Curate → Transform → Library`,D-019)
> Branch inspected: `cursor/cloud-top-tier-integration-f036` @ `11a7933fbf7bfab27ab040380b01647dd63a25b1`
> Production code changed by this round: **none**(research only)
> Status: 研究报告,供 Adversarial Reviewer(角色 C)与后续实验轮攻击/验证

---

## 0. 本轮证据基线(先于一切结论)

本轮在 Linux Cloud VM 上独立复现了仓库声明的验证结果,不沿用文档口径:

| 检查 | 结果 | 等级 |
|---|---|---|
| `python3 -m pytest -q --ignore=tests/test_pixiv_selector_probe.py` | `1155 passed, 68 skipped, 127 subtests passed in 14.58s`,0 failed | E2 |
| `python3 scripts/product_quality_gate.py --json` | `p0=0 p1=0 p2=0, ok=true` | E2 |
| `python3 -m compileall -q -x "runtime|\.venv|node_modules|data" .` | 通过 | E1 |
| `python3 scripts/scan_sensitive.py --git-candidates --content-only` | clean | E2 |
| `python3 scripts/bench_gallery.py --count 1000 --repeats 20` | `p50=0.269ms, p95=0.296ms, max=46.0ms`(synthetic in-memory) | E3-synthetic,**不是 10k/100k 声明** |
| 生产代码静态审计(四个独立探索:Acquire / Curate+Library / Transform / Butler) | 见下文逐条引用 | E1 |

与 `STATUS.md` / `CLOUD_CHECKPOINT_REPORT.md` 的声明一致,声明可信。Windows 真机、真实 NAI 付费、真实大图库仍为 **UNKNOWN**(与 `PENDING_LOCAL_WINDOWS.md` 一致,本报告不假装)。

---

## 1. Protected Strengths 验证(逐项给代码证据)

任务书要求保留率接近 100%。本轮逐项核实这些能力**当前真实存在**且有测试锁:

### 1.1 批量换角色(核心差异化,禁止丢失或退化)— 已核实,KEEP

完整链路(E1):

```
nai_char.extract_chars(_extract_chars_impl ← MetadataSourceRegistry / GalleryMetadataAdapter,PNG 回退 snapshots.comment_from_png)
  → nai_char.transform(replace* / replace_multi / clone / creature_to_partner;v4_slots / char_markers / ark 布局)
  → nai_char_modules/remix.compile_remix_recipe(extract → transform → style → sanitize → apply_generation_settings)
  → routes/char_swap.api_char_swap_batch_run → nai_batch.start_batch(patched_comment deepcopy + frozen_comment=True,点击时冻结)
  → nai_batch._process_target → nai/generate.generate_image → nai_char_modules/generation.build_generate_payload(唯一编译点)
  → generated_gallery.register_generated(.meta.json 含 prompt_snapshot / pipeline_steps)
```

关键机制(E1):
- v4 多角色槽:`_resolve_prompt_layout` 优先 `v4_prompt.caption.char_captions`;`_patch_comment` 回写正负向槽并对齐;clone 上限 6 槽。
- 性别:`slot_gender.resolve_slot_genders` / `apply_slot_genders`(槽 caption 与 base `1girl/1boy` 联合打分);`replace_multi` 支持每槽独立 gender/mode + identity guard。
- 动作保留:运行时默认 `preserve_action=True`;OC 路径 `merge_bundle` 强制保留姿势/神态/场景。
- 排队漂移防护:`start_batch` 点击时深拷贝冻结 comment,`_process_target` 优先用冻结草稿。

E2:`tests/test_nai_generate_compile.py`、`tests/test_nai_param_snapshots.py`、`tests/test_generation_jobs.py` 全绿(本轮复现)。

**结论:标 Protected Strength,任何候选改动(尤其统一 DAG / Canonical Asset Model)不得拆散 `transform → prepare_work_draft → start_batch → generate_image` 链路。**

### 1.2 付费/扣费语义 — 已核实,KEEP(但有一处默认值分裂,见 §4.3)

- `billing_uncertain` 不可自动重试:`nai_batch._is_retryable_failure` 显式排除;`partition_retry_targets` 把 `billing_uncertain`/`unknown`/崩溃恢复项归 `needs_review`(E1+E2)。
- 崩溃恢复:`generation_jobs.GenerationJobManager._restore_locked` 把磁盘 `running` → `unknown` + `recovered_after_restart=True`,文案「可能已扣费,不要自动重试」(E2:`tests/test_generation_jobs.py`)。
- 账本:`usage_ledger.record_usage` 失败吞异常返回 0,避免把已扣费成功变成可重试失败(E1)。
- 编译层 `force_free=True` 默认;有 image/mask/reference 则 `free_eligible=False`(E2:compile 锁测试)。

### 1.3 Butler 耐久核 — 已核实,KEEP

- SQLite 四表:`butler_tasks` / `butler_events`(`UNIQUE(task_id,event_key)`)/ `butler_receipts`(`operation_id` PK + `arguments_hash`)/ `butler_messages`(E1:`butler/store.py`)。
- 操作级幂等:`workflow_helpers._operation_identity` = `sha256(workflow_id:index:arguments_hash)[:32]`;`_execute_confirmed_node` 对 `succeeded` 回放、对 `started/unknown` 抛 `UnknownExternalOutcome` 禁止自动重放(E1)。
- 重启恢复:`recover_interrupted()` 把 `started` receipt 对应任务隔离为 `unknown/needs_review`,其余 `paused`;`resume()` 只允许 `paused`(E1)。
- Chat Tool Loop 边界:`ToolExecutor.execute` 对非 `interactive_executable` 工具零执行、只产 `WorkflowRequest`(E2:`tests/tooling/test_workflow_request_not_executed.py`);`planning.py` 零 import tooling(E2:AST 锁 `test_planning_module_still_does_not_import_kernel`)。
- 双人格分台:白名单双检(prompt 裁剪 `filter_plan_for_agent` + 执行期 `reject_foreign_tool` / `ToolContext.authorize`)(E2:`tests/test_butler_agents.py`)。

### 1.4 其他核实为 KEEP 的现有能力

| 能力 | 证据 | 判定 |
|---|---|---|
| NAI 准入门禁(拒 Comfy/SD) | 拖入/QQ/Pixiv Intake 三路全部过 `parse_nai_image` | KEEP,且应上提为 Acquire 适配器契约的一部分 |
| 三物理图库隔离 + `WorkRef` | `gallery_catalog.py`(site/codex/qqgroup 独立 DB+images_dir),D-004 冻结 | KEEP |
| 路径 jail | `paths.path_is_within`、`GalleryAssetStore._resolve_relative`、`gallery_index.resolve_index_image_path`(E2:越界反例测试) | KEEP |
| 整库快照备份/恢复 | `GallerySnapshotManager`:sqlite3.backup + manifest sha256 + `confirm=True` restore + rescue 回滚 | KEEP(灾难恢复粒度正确;细粒度 undo 是另一问题,§4.6) |
| Pixiv 失败分级 | `PixivAPIError.retryable`(429/≥500 + Retry-After)、指数退避+jitter 上限 300s、作品级 quarantine 账本、`pixiv_nai_receipts` | KEEP,应上提为适配器能力而非推倒 |
| 增量 FTS + rebuild 作 repair | `gallery_index.run_incremental` 脏集判定 + 批量上限 200/500;`rebuild_fts` 保留为修复 | KEEP |
| 脱敏/审计 | `redaction.py` 覆盖 store 启动/submit/checkpoint 边界;`butler_audit.jsonl` 无 raw secret | KEEP |
| v1.9 记忆/防打扰 | confirmed-only 召回、quiet hours 带时区、事件 dedupe/TTL/ack、FORBIDDEN_SOURCES 禁窥屏钩子 | KEEP |

**保留率结论:本轮未发现任何已丢失或退化的既有稳定功能;Protected Strengths 全部在位且有测试锁。**

---

## 2. Architecture Baseline v0 逐层评估

原则:Baseline v0 是优化对象,不重新发明。以下按层给出「现状 vs 基线」的差距,全部 E1。

### 2.1 Acquire

现状:**6 条活跃获取路径 + 1 条已禁用遗留**,无跨来源统一契约。

| 路径 | 入口 | 写库方式 |
|---|---|---|
| Pixiv App API / 公开 ajax / 浏览器 | `crawler_hub.run_pixiv` → `PixivNAISource` ← `PixivPublicWebSource` ← `PixivBrowserSource` | `PixivNAIIntake` 手写 SQL 直写 `data/aitag.db` |
| QQ 目录扫描 | `crawler_qq.crawl_once` → `qq_gallery_ingest.import_parsed_nai` | `upsert_local_work(GALLERY_QQ)` |
| 本地拖入 | `routes/gallery.api_gallery_import_drop` | `upsert_local_work`(codex/qqgroup) |
| Codex 批量导入 | `scripts/import_codex_gallery.py` | `upsert_local_work(GALLERY_CODEX)` |
| 遗留 site 爬虫 | `crawler.py` | **已禁用**(hub 返回 2,`start_crawler_target("site")` 抛错),代码仍在 |

与基线的差距:
1. **Provider 直写 Library DB**(D-019 明确要求禁止):`PixivNAIIntake` 与 `upsert_local_work` 都没有 Materialize 边界。这是 Baseline v0 相对现状最大的单一缺口。
2. **双写路径能力不对齐**:Pixiv Intake 有 receipts/多页/`source_sha256`/quarantine;`upsert_local_work` 一族没有等价物。新数据源只能整条复制其中一族。
3. **Pixiv 族有继承分层但无 capability 声明**:`fetch_page`/`download_original` 是类继承约定,不是 Protocol;无 health/rate-limit 契约。
4. **Watchdog 语义滞后**:`crawler_watchdog` 启停已指向 Pixiv PID,但完成判定仍用遗留 `crawl_state` phase 模型,心跳文件 `crawler-heartbeat.json` vs Pixiv 实际写 `pixiv-nai-intake-heartbeat.json`——进程守护与现网爬虫完成语义脱节。
5. 无全局 circuit breaker(有作品级 quarantine,属可接受的按需缺席,见 §5)。

### 2.2 Curate

现状:`search.py`(查询语言解析)+ `db_queries.search_works`(8 步组合查询)+ favorites/queue(`WorkSelectionStore` JSON)+ `gallery_index` dup/similar + aitag-online 在线发现。

差距/事实:
1. **Provider 字段泄漏进搜索层**:`db_queries` 用 `json_extract(list_json,'$.group_key'|'$.account_key')` 过滤(QQ/codex 语义);`cover_rel_path_from_list_json` 假设 Pixiv 的 `AI_type`+`userId` 目录布局;`list_json` 存 Pixiv camelCase(`userId`/`userName`)与 `x_restrict`。
2. 文本搜索 `total=None`(诚实但 UI 无总数);exclude 走 `LIKE`/`NOT EXISTS` 非 FTS NOT。
3. `find_near_duplicates` 有 dHash 高 16-bit 分桶;**`find_similar` 是全表扫描** hashes 取 `min(phash,dhash)`,规模化后是已知瓶颈(尚无 E3 证明疼痛阈值)。
4. `gallery_cache` 进程内 dict,仅 TTL,**无容量上限/LRU**。

### 2.3 Transform

现状:换角色 Recipe 链(§1.1)、Studio 单张、Director、post_pipeline(Lanczos 超分 → 可选 ANR 打码 → metadata,ANR 缺失降级 `mosaic:unavailable` 不阻断)、批量队列(`GenerationJobManager` 耐久 JSON + 并发/退避/部分失败/恢复)。

差距/事实:
1. **无统一 Pipeline/Recipe/DAG**:换角 Recipe、Director job、post_pipeline、Studio snapshot 各自为政。任务书立场是「是否引入更完整 DAG 必须通过实际需求和验证决定」——本轮判定为 **暂不引入**(理由见 §5.8)。
2. transform history 只有碎片:`.meta.json` 的 `prompt_snapshot`/`pipeline_steps`、job `items[]`、butler recipe payload;**图库 SQLite 没有 parent→recipe→output 血缘表**(`lineage.recipe_object` 现评 2.0,是全矩阵最低的非核心桶)。
3. `post_pipeline` 批任务状态机是进程内 `_JOB`,不如 generation jobs 耐久。
4. 配置默认值分裂(详见 §4.3)。

### 2.4 Library

现状:三 gallery SQLite + `images_dir` + `GalleryAssetStore`(WebP、quota、orphan 隔离)+ snapshot + generated 旁路树。schema 演进 = `SCHEMA_VERSION=2` + `PRAGMA user_version` 检查(新于代码只 warning 不降级)+ `_ensure_columns` 追加列;不是完整 migration 框架,但对当前 additive 演进方式足够。

差距:**没有正式的 `Remote / Cached / Materialized` 生命周期**。实际存在三套暗态:本地三库(≈Materialized)、aitag-online 收藏引用(`gallery_id=aitag-online` + `_favorite_snapshot`,不写 `aitag.db`,≈Remote 引用)、`DiskResponseCache`(TTL+max_bytes,发现用,≈Cached)。语义存在但无统一状态字段——这证明 Baseline v0 的三态假设**方向正确且已有种子**,不需要发明,需要显式化。

### 2.5 Provider / Provenance

- Provenance 现状:Pixiv 路径最完整(`works.source_url`、`user_id/user_name`、页级 `source_url/source_sha256/source_page_index`、receipts);QQ 记在 `list_json.source=qq-crawler:{group}:{account}` + `qq_ingest_files` 账本,**列级 `source_url` 通常不写**;拖入只有 `source=local-drop:{folder}`。acquisition time 有(`crawled_at`);author/rights/license 只有 Pixiv 部分;parent asset / recipe history 缺(§2.3)。
- 结论:provenance 是**不均匀**而非缺席。最小改动是把各路径已有字段收敛为同一组必填列,而不是新建 Knowledge Layer。

### 2.6 Butler / workflow(横向)

耐久与安全核已成型(§1.3)。真实差距:
1. **双执行面未收敛**:默认 LangGraph,`BUTLER_ENGINE=legacy` 仍走 `run_chat` 内存 `_PENDING`;`tooling/__init__` 自述「Not wired into LangGraph yet」。Kernel 与 durable workflow 并行,不是单一 Tool Loop。
2. **副作用执行是直连 import**:`auto_exec`/`execute`/`workflow_executors` 直接 `from nai_batch/crawler_control/...` import,确认门在 Butler 侧、执行体散落各子系统,无 Port/Adapter。
3. **风险标签两套语义**:`data/butler_catalog.json` 里 `generate_image` 是 `confirm`,`catalog_projection.PAID_TOOLS` 再升为 `cost`。
4. Audit 走旁路 JSONL 而非 store 事务(可接受,记录在案)。

---

## 3. 横向能力 15 项逐项判定(任务书 §3)

| # | 能力 | 判定 | 依据(证据等级) |
|---|---|---|---|
| 1 | Universal/Canonical Asset Model | **不做大一统重写**;以 `works`/`work_images` 为事实资产模型,补列不换模型 | 三库 schema 已稳定支撑全部功能(E1);推倒 = Big Bang,违反硬边界 1 |
| 2 | RemoteAssetRef vs LocalAsset lifecycle | **做,最小化**:显式化已存在的三态种子(§2.4) | aitag-online 收藏已是 remote ref(E1);缺统一字段 |
| 3 | Canonical Metadata/Tag/Alias 多语言知识层 | **LATER**;`tag_translate.py`/`nai_tag_index.py`/`knowledge_catalog.py` 已覆盖当前需求 | 无用户价值证据支撑新建知识层(E0) |
| 4 | Provider capability negotiation | **LATER**;先要统一写入契约,谈判协议只有 1.5 个 provider 时是过度设计 | Pixiv 族 + 本地族(E1);任务书 §4「不为覆盖清单建设施」 |
| 5 | Multi-provider Ranking | **LATER**,同上 | E0 |
| 6 | Cache Manager | **不建统一 Cache Manager**;只修 `gallery_cache` 无上限一点 | `DiskResponseCache` 已有 TTL+max_bytes(E1);统一层无需求证据 |
| 7 | Provenance / lineage | **做,P1**;收敛必填来源列 + 生成时写 parent/recipe 引用 | 现状不均匀(E1);ROADMAP 已列 Recipe 对象;矩阵 2.0 最低分 |
| 8 | Transform Pipeline/Recipe/DAG | **不引入统一 DAG**;保留各链路,先补 lineage 记录 | 换角链是 Protected Strength(E1/E2);DAG 收益无证据(E0) |
| 9 | Plugin capability/isolation | **REJECTED(本阶段)** | 硬边界 5 禁止任意插件 |
| 10 | Schema migration/backup/rollback | **现状够用 + 一项验证欠账**:additive 迁移 + 整库快照已有(E1/E2);缺 D-019 落地时的 migration rehearsal(E3) | §6 失败场景表 |
| 11 | Observability / failure taxonomy | **半做**:失败分类已分散存在(retryable/quarantine/billing_uncertain/unknown/ErrorEnvelope.code);不建观测平台,建议只统一错误码枚举文档 | E1 |
| 12 | 10k/100k/1M 性能 | **UNKNOWN**,Windows WIN-010 欠账;云端只有 synthetic(E3-synthetic) | 本轮 bench p50=0.27ms 仅为回归锚点 |
| 13 | Provider outage/API change/CORS 降级 | **部分有**(429/5xx/backoff/quarantine E1;分库隔离 E1);**缺 E3 故障注入**证明「Provider 单点失败不拖垮 Local Library」 | §6 |
| 14 | Local+Remote 联合搜索 | **LATER**;aitag-online 与本地搜索现为两条 UI 路径,联合搜索需先有三态字段(#2) | E1 |
| 15 | 现有功能兼容适配 | **持续硬约束**:`/api/ai_works_search` JSON 冻结、`WorkRef` 两字段、search-source freeze 测试在位 | E2 |

---

## 4. 真正值得修改的问题(候选改进,供对抗审查)

按任务书要求,每项给证据等级、迁移风险、验证方法、rollback。排序 = 用户价值 × 风险 ÷ 复杂度。

### 4.1 P1:Materialize 写入契约 + 「Provider 禁止直写」守卫

- 问题:Pixiv Intake 与 `upsert_local_work` 双路径直写 SQLite,能力不对齐,新 provider 无法低成本接入(E1,§2.1)。这是 Freeze Gate 条款「新 Provider 不需要持续修改核心业务」的直接阻塞。
- 最小改动:不重写任何现有 intake。第一步只做两件事:(a) 定义单一 `materialize_asset(...)` 入口(以 `upsert_local_work` 为种子,补 Pixiv Intake 的 receipts/sha256/多页能力);(b) 加守卫测试:除 materialize 模块外,任何 `pixiv_*`/`crawler_*` 模块不得出现 `INSERT INTO works`(AST/文本锁,模式同 planning import 锁)。Pixiv Intake 在第二步单独迁移。
- 迁移风险:中。Pixiv 写路径改动可能破坏 receipts 幂等;需保持 `pixiv_nai_receipts` 语义逐字节不变。
- 验证:provider 契约测试 + no-direct-write 守卫 + 现有 `tests/test_pixiv_nai_crawler.py` 全绿 + 双路径写入结果 diff(同一输入 → 同一行)。
- Rollback:守卫测试可单独 revert;materialize 函数是 additive,旧路径保留到 diff 验证通过。
- 证据等级:问题 E1;改动收益需 E2(契约测试)。

### 4.2 P1:来源三态显式化(additive 列,不迁移数据)

- 问题:Remote/Cached/Materialized 语义存在但无字段(§2.4),Local+Remote 联合搜索、收藏失效降级都被它阻塞。
- 最小改动:`works` 或 `gallery_index_files` 增 `lifecycle` 列(additive,`_ensure_columns` 模式),现有行默认 `materialized`;aitag-online 收藏项在 JSON 里补 `lifecycle:"remote"`。不做任何回填迁移。
- 迁移风险:低(纯 additive;老版本代码读新库因 user_version 只 warning,不损坏)。
- 验证:remote-reference vs materialized 测试(D-019 验收清单已列);旧库打开兼容测试。
- Rollback:`ALTER TABLE` 列留存无害,读方 revert 即可。
- 证据等级:问题 E1;需 E2。

### 4.3 P1:付费/换角配置默认值对齐 + 服务端付费确认

- 问题(E1):`char_swap_config.DEFAULTS` 中 `force_free=False`、`preserve_action=False`,与 API/运行时默认 `True` 相反;付费闸门主要在前端(`RemixPage.tsx` 拦截 + `window.confirm`),API 调用方可直接 `force_free=False` 无服务端二次确认。自动化路径(Butler auto、脚本)易踩坑。
- 最小改动:对齐 DEFAULTS 为安全侧(`force_free=True`/`preserve_action=True`);服务端在 `force_free=False` 且无确认票据时拒绝(复用现有 WorkflowRequest/confirm 票据,不发明新机制)。
- 迁移风险:低,但要排查依赖旧默认值的存量配置文件(用户 config 显式值不受影响)。
- 验证:反例测试「未确认付费请求被服务端拒绝」;现有 compile 锁不变。
- Rollback:revert 常量 + 拒绝分支。
- 证据等级:问题 E1;需 E2。**这是「不得削弱付费确认」硬边界的正向补强。**

### 4.4 P2:Provenance 必填列收敛 + 生成血缘最小落库

- 问题:QQ/拖入不写列级 `source_url`;生成图 parent/recipe 只在 `.meta.json`(§2.5)。批量换角色派生关系不可查询。
- 最小改动:(a) 三条写入路径统一填 `works.source_url` 与 `work_images.source_sha256`(QQ/拖入用本地 URI 约定);(b) `register_generated` 时把 `source_work_ref` + `recipe_id` 写入 generated meta 的**固定键**,暂不建新表——等 4.1 契约落地后再决定是否升表。
- 迁移风险:低(写路径 additive;不回填历史)。
- 验证:provenance persistence 测试(D-019 验收清单);换角批量后能从成图查到源图引用。
- Rollback:revert 写入点。
- 证据等级:问题 E1;需 E2。

### 4.5 P2:Watchdog 语义对齐现网爬虫

- 问题(E1):守护判定用遗留 site phase/心跳文件,Pixiv 实跑 `pixiv-nai-intake-heartbeat.json`——爬虫卡死可能既不被发现也不被正确重启。
- 最小改动:watchdog 读 Pixiv 心跳与 quarantine 账本;遗留 `crawler.py` 完成语义标记 deprecated(不删,入口已关)。
- 迁移风险:低。验证:心跳停止 → watchdog 反应的故障注入测试(顺带补 §6 的 provider outage E3)。Rollback:revert watchdog 读取点。

### 4.6 P2:`find_similar` 分桶 + `gallery_cache` 上限(小修)

- `find_similar` 复用 near 已有的 16-bit 分桶(E1 证明模式已存在);`gallery_cache` 加条目上限。
- 风险低;验证:相似结果等价性测试 + 未来 WIN-010 真机 bench。10k 疼痛阈值目前 UNKNOWN,故列 P2 不是 P1。

### 4.7 P2:Butler 双执行面收敛(v1.8 延续,不新开工程)

- 问题(E1):legacy `run_chat` 内存 `_PENDING` 与 LangGraph 并存;catalog `confirm` vs projection `cost` 两套风险标签。
- 最小改动:风险标签以 `catalog_projection` 为准回写 catalog;legacy 引擎标记 deprecated 并在测试锁「legacy 与 langgraph 对同一 cost 工具行为一致」。**不**移除 legacy(回退通道价值)。
- 风险:中(chat 行为面)。验证:现有 tooling 测试 + 新增一致性测试。Rollback:revert 标签与锁。

### 明确 KEEP(不修改,防止后续轮次重复提案)

1. 三库物理隔离与 `WorkRef` 两字段(反方案「统一单库」REJECTED:破坏隔离、迁移风险大、无收益证据)。
2. 换角色链路与编译边界(§1.1)。
3. `billing_uncertain`/`unknown` 隔离语义与 receipts 幂等(§1.2/1.3)。
4. 整库 snapshot 作为灾难恢复;细粒度 move journal 按 `GALLERY_INDEX_DESIGN.md` Phase D 排期,不提前。
5. FTS `total=None` 的诚实 COUNT(反方案「估算总数」在无 E3 前 REJECTED)。
6. `search.py` 解析器现状(嵌套布尔不完整是已知限制,无用户价值证据前不扩)。
7. 不引入统一 Transform DAG、插件系统、Cache Manager、capability negotiation(§3)。

---

## 5. 木桶 Capability Matrix 增量(相对 `CAPABILITY_MATRIX.md`)

本轮不改 Lead 所有的 `CAPABILITY_MATRIX.md`,以下为研究侧增量意见(评分口径不变:8=对本产品可生产):

| capability_id | 现分 | 本轮证据后的意见 | 置信度 |
|---|---:|---|---|
| `post.pipeline` | 6.0 | 维持 6.0;ANR 依赖是产品决策不是架构缺陷,替代打码方案属 Windows 轮 | 高(E1+E2) |
| `assist.proactive_events` | 6.0 | 维持;v1.9 机制完整,分数受限于无真实使用证据(E4 缺) | 高 |
| `lineage.recipe_object` | 2.0 | 维持 2.0,但升优先级:它同时阻塞 provenance、可复现与换角派生查询(§4.4) | 高(E1) |
| `assist.tool_loop` | 7.0 | 维持;双执行面(§4.7)是到 9.0 的主要阻塞 | 高(E1+E2) |
| `search.fts_works_prompt` | 7.5 | 维持;COUNT/exclude 是已知限制,10k 前不动 | 高 |
| `ingest.*`(新建议行) | — | 建议下轮新增 `acquire.provider_contract` 行,现状约 5.0(路径能用但无契约,弱于基线要求),target 8.0,对应 §4.1 | 中(E1) |
| `recover.generation_unknown` | 8.0 | 证据充分(E2 复现),可信 | 高 |
| `start.loopback_trust` | 9.0 | 维持,Protected Strength | 高 |

木桶方法自审(任务书 §4 要求):当前矩阵的主要方法论风险是 **(a)** 桶间耦合未显式化——`lineage.recipe_object`(2.0,core=N)实际阻塞多个 core 桶的提升,单看 core 最低分会低估它;**(b)** 多数分数的置信度来自 E1/E2,`start.one_click_launch`/性能类分数在 Windows 真机前都应标注低置信度;**(c)** 无对照组——建议下轮 Barrel Researcher 对 `acquire.provider_contract` 与 `lineage` 两桶做 Best-of-Breed 对标(候选:IIB 的索引契约、Langbai 的项目恢复,只读行为不抄源)。

---

## 6. 关键失败场景证据状态(任务书 §8)

| 场景 | 现有防护 | 证据 | 缺口 |
|---|---|---|---|
| Provider 429/5xx/timeout | retryable 分级 + 指数退避 + quarantine | E1+E2(pixiv crawler 测试) | 无 E3 长时故障注入 |
| Provider outage 拖垮 Library | 分库隔离 + 爬虫独立进程 | E1 | **无 E3**;Freeze Gate 条款依赖它,下轮应做:杀死/断网爬虫进程,验证图库读写不受影响 |
| SQLite lock/corruption | WAL + busy_timeout 30s + 写 RLock | E1 | 无 corruption 注入测试 |
| DB/文件部分写入 | receipts started→unknown;`atomic_io` | E1+E2 | — |
| migration 中断/旧版回退 | user_version 只 warning 不降级;快照可回滚 | E1 | D-019 实施时需 migration rehearsal(E3) |
| NAI 已扣费结果未知 | `billing_uncertain` + `running→unknown` + needs_review | **E2**(本轮复现) | 真机 E4 未验证(WIN-012) |
| 批量换角色部分失败 | 逐项计数 + `partition_retry_targets` | E2 | — |
| Transform crash | generation jobs 耐久;post_pipeline `_JOB` 进程内 | E1/E2 | post_pipeline 崩溃恢复弱于 generation(§2.3) |
| cache 爆满/disk full | AssetStore quota/`has_capacity`;gallery_cache 无上限 | E1 | §4.6 |
| 100k+ 性能 | 分页两步取、FTS、分桶(near) | E3-synthetic only | WIN-010 |
| Remote 收藏来源失效 | `_favorite_snapshot` 保底元数据 | E1 | 无失效降级 UI/测试 |
| provenance 缺失 | Pixiv 完整,QQ/拖入不均 | E1 | §4.4 |

---

## 7. Architecture Freeze Gate 判定

逐条对照任务书 §10:

| 条款 | 判定 | 依据 |
|---|---|---|
| 现有稳定功能保留 ≈100% | ✅ 满足 | §1,本轮全量测试复现 |
| 用户资产兼容/迁移可回滚 | ✅ 当前满足 | 整库快照 + additive schema;D-019 实施时需 rehearsal |
| 批量换角色等 Protected Strength 不退化 | ✅ 满足 | §1.1,E1+E2 |
| 无未解决 P0/P1 架构风险 | ❌ **不满足** | P1×3:Provider 直写契约缺失(4.1)、三态缺失(4.2)、付费默认值分裂(4.3) |
| Provider 单点失败不拖垮 Library | ⚠️ E1 支持,**无 E3** | §6 |
| 关键迁移/失败假设有 E2/E3 | ⚠️ 部分 | 扣费/恢复 E2 ✅;性能/outage/migration E3 ❌ |
| 核心桶无 <8.5 高价值短板 | ❌ 不满足 | 木桶 6.0(post.pipeline / proactive_events);多桶 7.x |
| 差异化关键桶 ≈9+ | ❌ 不满足 | 换角色链路实现强但整桶(批量生产 8.0)未到 9,受 lineage/真机验证拖累 |
| 新 Provider/Processor 低成本扩展 | ❌ 不满足 | §2.1 双写路径 |
| 连续两轮只有局部优化 | ❌ 本轮仍有架构级发现 | §4.1/4.2 |
| 继续优化收益 < 成本 | ❌ 不成立 | P1 三项均为小改动高收益 |

**结论:不冻结。**但同样明确:**不需要任何推倒式架构工作**。本轮全部候选都是 additive/局部改动,Baseline v0 的四层划分与现有代码高度吻合(三态、provenance、provider 契约都已有种子实现),基线本身经受住了代码证据的检验,应保持为 v0 不动。

## 8. 下一轮算力分配建议(任务书 §6)

1. **Adversarial Reviewer(C)攻击本报告 §4.1–4.3**:重点找 materialize 契约会破坏 Pixiv receipts 幂等的反例、三态列与旧版本共存的反例、服务端付费闸门误伤合法自动化的反例。
2. **E3 实验(优先级最高的 UNKNOWN)**:provider outage 故障注入(杀爬虫进程/断网 → 图库可用性);D-019 三态列的 migration rehearsal(旧库 → 新代码 → 回旧代码)。
3. **Barrel Researcher(B)只对两桶对标**:`acquire.provider_contract`(IIB/Danbooru-client 类项目的 source 契约,读代码不抄)与 `lineage.recipe_object`(ComfyUI workflow 存储、Langbai 项目恢复的血缘 schema)。
4. **不投算力**:统一 DAG、插件系统、Cache Manager、多 provider ranking、语义搜索(§3 已判 LATER/REJECTED,除非 C 拿出反证)。
5. Windows 真机项(WIN-001..015)不占本研究循环算力,按 `PENDING_LOCAL_WINDOWS.md` 走本地接管。

---

## 附:本轮研究的证据边界声明

- 本报告全部结论基于 Linux Cloud VM 上的静态代码审计(E1)、测试复现(E2)与合成微基准(E3-synthetic)。
- 未运行付费 NovelAI 请求,未接触真实用户图库,未做 Windows 验证——凡依赖这些的结论均已标 UNKNOWN。
- 未修改任何生产代码;本文件是本轮唯一交付物。
- `Manga-Editor-Desu-NAI` 未被连接、审计或对标(D-006)。
