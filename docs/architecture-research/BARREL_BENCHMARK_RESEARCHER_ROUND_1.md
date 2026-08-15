# Barrel Benchmark Researcher · Round 1

> Role: **B — Barrel Benchmark Researcher**  
> Method: Capability-based Benchmarking + Gap Analysis + Best-of-Breed + Constraint-driven Improvement + Regression Gates  
> Baseline: Architecture Baseline v0；不重做总体架构  
> Production code changed: **none**  
> Open-source study: behavior and published schema/code only. **Do not copy AGPL/GPL into this MIT tree.**

本报告建立横向能力桶，优先高价值短板。标杆只提高该桶标准，不整体模仿任何项目。Nai学长已经更强或更适配的能力标为 Protected Strength。

评分口径与 `CAPABILITY_MATRIX.md` 对齐：0 无，5 通路弱于对标，8 对本产品可生产，10 有证据的领先。木桶分 = 该桶当前分。Confidence：高 = E2+，中 = E1，低 = E0/未知测量。

---

## 0. 现有产品木桶（不重评分，只作约束）

`CAPABILITY_MATRIX.md` 核心最低分仍是 **6.0**（`post.pipeline` / `assist.proactive_events`）。本轮架构研究**不重开 Phase 0 评分**，也不把 TTS 拉进木桶。

Protected Strength（对标时禁止拉低）：

- 批量换角色（preview → confirm → run → 部分失败可重试、身份守卫、付费冻结）
- 付费/unknown 语义
- NAI-only 准入
- 三库隔离 + `WorkRef`
- 本机信任（loopback / DPAPI 合同 / 路径 jail）
- 单一 NAI 客户端
- Tool Kernel 不执行副作用

这些桶即使对标项目“更有名”，也不得用对方模型替换。

---

## 1. 横向 Capability Matrix（相对 Baseline v0）

| ID | Capability | Current Evidence | Score | Conf. | User Value | Risk if wrong | Decision |
|---|---|---|---:|---|---|---|---|
| C1 | Canonical Asset Model | `WorkRef` + per-gallery `works.id` + `image_key`；无跨层 Asset 类型 | 6.5 | 中 | 高 | 换身份会打 favorites/换角色 | 薄类型，不换存储 |
| C2 | Remote / Local / Materialized | 旗标 + AITag cache + receipts；无命名三态 | 5.5 | 中 | 高 | 自动下载违背 D-019 | 只读投影 |
| C3 | Metadata / Tag / Alias / i18n | `nai_tag_facets` 8 面；无 sibling/alias 层；`web/tag_i18n.js` 展示向 | 7.0 | 中 | 中 | Hydrus 级别名会拖垮导入 | KEEP facets；alias LATER |
| C4 | Provider capability negotiation | Pixiv 有 delay/retry/quarantine；无统一 capability 对象 | 5.0 | 中 | 中 | 过度协议化 | 薄描述符 |
| C5 | Multi-provider Ranking | 仅 site monthly bookmarks | 3.0 | 高 | 低 | 污染 NAI-only | REJECT 本轮 |
| C6 | Cache Manager | 多套 TTL；`work_lite` 写入不失效；AITag 磁盘缓存独立且健康 | 5.5 | 中 | 中 | 统一总线过工程 | 只补失效 |
| C7 | Provenance / lineage | Pixiv URL/sha256 强；QQ/drop 弱；generated sidecar 部分；无 recipe 对象 | 4.5 | 中 | 高 | 影响换角色复现 | ADD sidecar |
| C8 | Transform Pipeline / Recipe | `compile_remix_recipe` 顺序编译 + 线性 post_pipeline；无 DAG | 7.5 | 高 | 高 | DAG 会伤换角色 | KEEP；recipe fingerprint only |
| C9 | Plugin capability / isolation | 模块边界 + 前端 DAG 测试；同进程无沙箱 | 6.5 | 高 | 中 | 沙箱破坏换角色 | KEEP 模块边界 |
| C10 | Schema migration / backup / rollback | site snapshot + WebP 单行 rollback；codex/qq 无备份 | 6.0 | 中 | 高 | 旧库不可回滚 | 复用 snapshot |
| C11 | Observability / failure taxonomy | 付费 taxonomy 强；fault_injection 名不副实；ledger 静默失败 | 7.0 | 高 | 高 | 乱重试会扣费 | 小补强 |
| C12 | 10k / 100k / 1M | 合成 bench only；WIN-010 queued | 2.0* | 低 | 高 | 假成绩 | UNKNOWN，先测 |
| C13 | Provider outage / API / CORS / 429 | 付费路径强；Acquire 各管各的；本地库已隔离 | 7.5 | 高 | 高 | 远程失败拖垮本地 | KEEP 隔离 |
| C14 | Local + Remote 联合搜索 | 不存在；单 `gallery_id` | 2.0 | 高 | 中 | CORS/loopback/权限 | 后置 |
| C15 | 现有功能兼容适配 | 冻结接口 + 大量合同测试 | 8.5 | 高 | 极高 | 任何重写 | KEEP / regression gate |

\*C12 的 2.0 表示**测量缺失**，不是查询实现只有 2 分。查询形状本身约 7.5（见现有 `search.fts_works_prompt`）。

**本轮优先补强的桶：** C7、C2、C1（薄）、C10、C6（失效）、C4（薄）、C12（测量）。  
**明确不磨到 10 的桶：** C5、C8（已 7.5+）、C9、C3。  
**Protected / 已够用：** C8、C11 付费子集、C13 本地隔离、C15。

---

## 2. 选中短板的 Best-of-Breed

每个桶单独选标杆。阅读了对方公开 schema / 文档 / 源码片段，而不是只看 README。

### 2.1 C1 / C2 资产身份与三态

**标杆 A — Hydrus Network（WTFPL）**

为什么强：

- 文件主身份是 SHA-256；tags / notes / known URLs 挂在 hash 上，删文件后元数据仍在“幽灵”上，再导入可恢复。
- `known URLs` 把远程地址和本地文件分开：遇到已见 URL 可跳过下载。
- 文件关系：duplicate group 只保留一个 King；alternates 是组间关系，不做全对全 better/worse。
- 源码：`ClientDBFilesStorage.py` 按 service 拆 `current/deleted/pending` 表；`ClientDBURLMap` 做 URL↔hash。

适合 Nai学长：

- **URL 与文件分离**（RemoteAssetRef ≠ LocalAsset）。
- **hash 作为辅键**做精确去重（已有 `source_sha256`）。
- **不自动删重复文件**；展示关系，用户确认。

不适合：

- 用 hash 替换 `WorkRef` / Pixiv id。用户按作品、账号、页思考，不是按 blob。
- 完整 duplicate King 系统 + auto-resolution。维护成本和误杀风险高于本产品规模。
- Public Tag Repository / 多 service 同步。违背 local-first。

许可证：WTFPL，可借鉴思想。不要搬 schema 或模块切分。

**标杆 B — Immich（AGPL，只看行为）**

为什么强：

- `isExternal` + `originalPath` 区分“库内物化”和“外部扫描引用”。
- External library 默认可只读挂载；扫描创建资产，删源文件则资产消失，搬回则重新出现。
- 物化（external → internal）是显式迁移，不是浏览副作用。

适合：

- **浏览外部/远程 ≠ 拥有**。这正是 D-019 的 `Add to My Library`。
- 物化必须是显式动作。

不适合：

- Docker/Postgres 栈。
- 把 Codex/QQ 当 Immich external library（它们已经是本地物化库）。
- AGPL 代码。

**标杆 C — IIB `ExtraPath`（Apache-2.0）**

源码 `scripts/iib/db/datamodel.py`：

```sql
CREATE TABLE image (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE,
  exif TEXT,
  size INTEGER,
  date TEXT,
  exif_edited INTEGER DEFAULT 0
);
CREATE TABLE extra_path (...);
```

身份是**文件系统路径**，额外根目录用 `ExtraPath` 挂上。增量索引按文件夹 mtime；20k 图约 45s 是作者机器叙述，不是本仓库成绩。

适合：路径/mtime dirty 谓词（本仓库 `gallery_index_files` 已有 size/mtime/sha/parser_version，更严）。  
不适合：用 path 当跨库主键；IIB 服务 SD/Comfy 输出目录，本产品拒 Comfy。

**本桶机制借用：**

```text
RemoteAssetRef { provider, remote_id, source_url?, rights? }
  --explicit user action-->
LocalAsset    { gallery_id, work_id, page_index, sha256?, local_path }
```

收藏可只存 `RemoteAssetRef`。物化走现有 `upsert_local_work` / Pixiv intake，不新建表当主存储。

What NOT to borrow：Hydrus 主身份、Immich 云同步、IIB embedding 默认路径。

---

### 2.2 C7 Provenance / lineage

**标杆 A — Hydrus known URLs + file relationships**

- 远程出处是一等数据，不是 list_json 里的字符串。
- 派生/重复是显式关系，不是靠文件名猜测。

**标杆 B — 本仓库已有的 generated sidecar（自家长板）**

`generated_gallery.register_generated` 已写 `source_gallery_id`、`generation_series_id`、`prompt_snapshot`、`pipeline_steps`。缺的是配方指纹和父生成图。这比引入 C2PA 或 Comfy workflow JSON 更贴产品。

**标杆 C — C2PA / Content Credentials**

工业级签名溯源。对单机 NovelAI 工作室过重：要证书、私钥、验证链，且 NovelAI PNG 已有 Comment/stealth。  
Verdict: **REJECT** 作为本轮依赖。

**标杆 D — ComfyUI 图工作流嵌入**

本产品 `parse_nai_image` 明确拒 Comfy。不能为了 lineage 打开这扇门。

**机制借用：**

- 物化时强制写 `provider`、`remote_id`、`source_url`、`source_sha256`、`acquired_at`（Pixiv 已接近；QQ/drop 补齐）。
- 生成时 additive：`recipe_fingerprint`、`parent_generated_stem`、`transform_summary`。
- 关系查询走 sidecar / 未来小表，不改 `works` PK。

What NOT to borrow：C2PA 栈、Comfy 图、Hydrus 自动 King。

---

### 2.3 C4 Provider / Acquire Adapter

**标杆 — gallery-dl Extractor（GPL-2.0，只看机制）**

源码 `gallery_dl/extractor/common.py`：

- 站点逻辑在 Extractor 子类；`items()` 只 `yield Message.Directory | Message.Url | Message.Queue`。
- Job/download/archive 与站点无关。
- `request_interval` / `request_interval_429` 是类属性，不是全局协商协议。
- 新站点 = 新模块 + `pattern` + 测试结果文件。

适合：

- **消息/记录协议**：Provider 产出“远程作品描述 + 可选字节”，LibraryWriter 负责落库。
- 每源自己的 delay/429，不要一个全球 circuit breaker 服务。

不适合：

- 把 200+ 站点框架搬进来。本产品只收 NAI  provenance。
- URL regex 路由作为唯一发现方式（QQ 是文件夹，drop 是 HTTP 上传）。
- GPL 源码。
- archive 按 URL 去重替代 NAI parse gate。

**本仓库已有的局部标杆：** Pixiv 的 `PixivNAISource` / `PixivPublicWebSource` / `PixivBrowserSource` + `PixivNAIIntake.ingest_work`。应把这个缝推广，而不是换成 gallery-dl。

**薄 capability 描述符（建议，不实施）：**

```text
ProviderDescriptor
  id, kind: api|crawler|folder|drop|browser|online
  capabilities: search, detail, download_original, thumbnail_only
  auth: none|token|browser
  nai_gate: required
  writes_library: false
  rate: delay_sec, retry_max
```

这是文档+测试合同，不是运行时插件加载器。

What NOT to borrow：yt-dlp 格式选择器、OAuth 通用基类、动态插件发现。

---

### 2.4 C6 Cache

**标杆 A — 本仓库 `DiskResponseCache`（已是好设计）**

- HTTPS URL 内容寻址，TTL + max_bytes。
- 读失败 = miss，不挡本地图库。
- 无源索引，可整盘清。

这应标 **Protected 局部设计**，不要用“Cache Manager”把它吞掉。

**标杆 B — IIB embedding skip rule**

`image_embedding` 在 `model + text_hash + vec` 未变时跳过。思想与 `gallery_index` dirty 谓词同类。IIB 的 OpenAI embeddings **不借**（出网、费用、本产品 `local_none`）。

**标杆 C — HTTP RFC 9111**

对 AITag JSON 缓存够用；不要为缩略图搞 Vary/ETag 平台。

**机制借用：** mutation 失效 `work_lite`；保持 AITag 缓存独立。  
What NOT to borrow：Redis、跨进程 cache bus、默认向量缓存。

---

### 2.5 C8 Transform / Recipe

**标杆 A — 本仓库 `compile_remix_recipe`（Protected Strength）**

顺序确定、可测、与 `RemixPrimitives` 解耦。这已经比多数“工作流编辑器”更适合批量换角色。

**标杆 B — LangGraph（已在 Butler）**

付费/破坏性长任务已有 durable workflow。Transform 编译不应再套一层图。

**标杆 C — ComfyUI / InvokeAI 图**

强在通用生图实验，弱在本产品的身份守卫、冻结 comment、250 条批量合同。

**机制借用：** 只加 `recipe_fingerprint = sha256(canonical(recipe + frozen_comment + software_version))`。  
What NOT to borrow：节点编辑器、DAG 调度、第二套 workflow runtime。

---

### 2.6 C3 Tag / Alias

**标杆 — Hydrus siblings / parents**

- sibling：显示 ideal tag，存储仍可保留 raw。
- parent：子标签蕴含父标签，靠 lookup cache。

本仓库已有更贴 NAI 的东西：`nai_tag_facets` 把 character/copyright/artist/… 从已验证 `parsed_nai_tags` 抽出，character 还派生 copyright 后缀行（`derived=1`）。

Danbooru 别名表能补中英/多写，但：

- 维护成本高；
- 错误别名会让换角色匹配错角色；
- `web/tag_i18n.js` 已覆盖展示层一部分。

**本轮：** KEEP facets。Alias knowledge layer 标 **LATER**，除非有 E3 证明“搜不到角色”是高频痛。  
What NOT to borrow：PTR 同步、全量 Danbooru dump 随安装包分发。

---

### 2.7 C10 Backup / migration

**标杆 A — 本仓库 `GallerySnapshotManager`**

zip + per-file SHA256 + `PRAGMA integrity_check` + `confirm=True` restore + maintenance lock。这是正确粒度的**整库灾难恢复**。缺口是只绑 site。

**标杆 B — Immich 路径迁移脚本**

社区用 SQL 改 `originalPath`。Immich 官方不支持直接改库。说明“改路径要 journal”。本仓库 WebP migrate 已经按文件 staged + rollback copy，优于手写 SQL。

**机制借用：** 把 manager 参数化到三库；migrate 保持 per-file 事务。  
What NOT to borrow：Postgres dump、自动路径改写脚本。

---

### 2.8 C12 性能

**标杆 — IIB 作者叙述 20k / 45s 全量索引**

只能当数量级直觉，不能当本产品 SLA。IIB 按 path+mtime；本产品还要 NAI parse、WebP、FTS、dHash。

Hydrus 在 10^5–10^6 靠 hash_id 整数和分表。本产品三库 + 每库 FTS 的目标是 10k–100k Windows，不是 1M 通用媒体库。1M 对本产品是 **错误目标**（用户是 NAI 创作者，不是全网镜像）。

**机制借用：** 保持 dirty-set；similar 用 hash 分桶（设计文档已写，实现是否分桶需读 `find_similar` 再测）。  
What NOT to borrow：把 IIB 45s 写成自己的成绩；为 1M 引入独立搜索引擎。

---

### 2.9 C14 联合搜索

**标杆 — Hydrus location context / Immich timeline 混合 internal+external**

对方能混搜是因为同一套资产表。本产品远程是另一协议（AITag HTTP），本地是三套 SQLite，generated 是扫盘。硬联合会变成 federated query。

**本轮 REJECT 实现。** 先做 RemoteAssetRef 投影和 UI 分区（Online vs My Library）。若以后做，也是“两次查询 + 合并 WorkRef 列表”，不是新索引。

---

### 2.10 C9 插件隔离

**标杆 — LingChat tool registry（AGPL，行为 only）**

本仓库已吸收：catalog、desk allow-list、WorkflowRequest。God Agent / hooks 已禁止。

VS Code 扩展沙箱、浏览器扩展隔离对 char-swap 无益：换角色必须同步读 gallery DB、写 generated、走同一 `GenerationJobManager`。

**Protected：** 模块线预算、前端 acyclic DAG、kernel 不执行付费。  
What NOT to borrow：进程隔离插件宿主。

---

## 3. 每个建议的最小改动（仍不实施）

| ID | 桶 | 最小改动 | 验证 | 许可/维护 | Regression |
|---|---|---|---|---|---|
| B1 | C7 | generated `.meta.json` 增 3 个可选字段 | 旧图缺字段仍可分组；换角色 batch 回归 | 无新依赖 | 低；读路径兼容 |
| B2 | C2/C1 | `RemoteAssetRef` dataclass + lifecycle 投影 | AITag 收藏不落盘；drop 仍立即物化 | 无 | 中；勿改 WorkRef JSON |
| B3 | C7/C4 | `upsert_local_work` 写 `source_sha256` / 可选 `source_url` | QQ/drop 合同测试 | 无 | 中；WebP 后 hash 语义要写清 |
| B4 | C4 | Provider 不得直写 DB 的守卫测试 + writer facade | 先 QQ/drop | 无 | 高若动 Pixiv SQL；故缓动 Pixiv |
| B5 | C10 | snapshot manager 接受 gallery_id | 临时 Codex 库 zip/verify/restore | 无 | 中；锁与 crawler stop 仅 site |
| B6 | C6 | 写路径 invalidate `work_lite` | 改 title 后 1s 内 lite 非旧值 | 无 | 低 |
| B7 | C11 | ledger 失败打到 job flag；corrupt jobs 测试 | 现有 generation 测试 + 新反例 | 无 | 低 |
| B8 | C12 | Windows 真机 bench 方案（见 candidate） | WIN-010 | 无 | 无代码风险 |
| B9 | C8 | `recipe_fingerprint` 纯函数 + 单测 | 键序稳定；未知字段不进指纹 | 无 | 低；勿改 compile 顺序 |

以上都不是新框架。任何一项若无法通过换角色/搜索冻结测试，则 REJECT 该项。

---

## 4. 木桶法自审（给 Reviewer）

本报告可能犯的错，请下一轮攻击：

1. **局部最优：** 补 provenance 若迫使换角色改 HTTP，就是错的。  
2. **评分主观：** C12=2.0 是测量缺失，有人会误读成“搜索很差”。  
3. **过度工程：** LibraryWriter 可能只是多一层空函数；若 facade 不减少 SQL 分叉，应 REJECT。  
4. **桶间耦合：** C2 三态 + C14 联合搜索 + C1 新类型容易滚成大改。必须拆波。  
5. **标杆光环：** Hydrus/Immich/IIB 更有名，不代表更适合 NAI 工作室。  
6. **忽略 Protected Strength：** 任何“统一资产模型”若让 `WorkRef.work_id` 变成 UUID/hash，换角色队列键 `gallery_id:work_id:page_index` 会裂。

---

## 5. 本轮不磨的高分桶

| 桶 | 为什么停 | 对标诱惑 |
|---|---|---|
| 付费失败分类 | 已 8 分量级，缺的是真机 E3 | SANP 更激进重试会更差 |
| 换角色 recipe 编译 | 已是差异化 | Comfy 图、通用 pipeline |
| NAI-only ingest | 产品身份 | IIB 收 SD/Comfy |
| loopback/CORS | 安全基线 | Immich 远程访问模型 |
| 分台助手 | 长板 | LingChat 单角色/God Agent |

---

## 6. 许可证记录

| 项目 | 许可 | 本轮用法 |
|---|---|---|
| Hydrus | WTFPL | 思想：URL≠file、hash 辅键 |
| Immich | AGPL | 行为：external vs 物化；不读不抄代码 |
| IIB | Apache-2.0 | schema/增量思想；不引入 embedding 出网 |
| gallery-dl | GPL-2.0 | 机制：Extractor 产消息；不引入源码 |
| LingChat / SANP | AGPL | 已在 COMPETITOR_BASELINE 规定行为-only |
| C2PA | 多许可/生态 | 不引入 |
| 本仓库 | MIT | 所有建议必须保持 MIT 可发布 |

---

## 7. UNKNOWN（测量后才能打分）

1. 10k 真库 incremental-100 / keyword p95 / similar p95 / 缩略图滚动 RSS。  
2. `find_similar` 是否已分桶；未分桶时 10k 是否可接受。  
3. QQ/drop 补 `source_sha256` 时，hash 的是导入原字节还是 WebP。设计文档要求优先原字节。  
4. 远程收藏死链的真实用户频率（无 E4）。  
5. LibraryWriter 是否降低、还是增加 Pixiv intake 的崩溃窗口复杂度。  
6. 三库 snapshot 在机械硬盘上的时间（云端无法代替）。  
7. 别名层是否真能提高换角色选角成功率。
