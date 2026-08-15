# Round 1 Handoff · 给下一位独立 Adversarial Reviewer

> 你是任务书角色 **C — Adversarial Reviewer**。  
> 不要再造一套宏大架构。  
> 不要改生产代码。  
> 专门尝试证明 Candidate v1 会失败。  
> 对合理设计明确写 KEEP。  
> 没有证据标 UNKNOWN。

阅读顺序：

1. `docs/top-tier-upgrade/MULTI_MODEL_ARCHITECTURE_RESEARCH_BRIEF.md`（方法与冻结规则）
2. `docs/top-tier-upgrade/DECISIONS.md` D-004 / D-012–D-019
3. `docs/top-tier-upgrade/CLOUD_CHECKPOINT_REPORT.md`（硬边界）
4. `docs/architecture-research/ARCHITECTURE_OPTIMIZER_ROUND_1.md`
5. `docs/architecture-research/BARREL_BENCHMARK_RESEARCHER_ROUND_1.md`
6. `docs/architecture-research/candidate-v1.md`（你的主攻击面）

仓库仍是 `h1neolzr7f/NaiXueZhang-Studio-Upgrade`。集成分支 `cursor/cloud-top-tier-integration-f036`。本轮研究在 `cursor/architecture-research-round1-0ce7`。不要合 `main`，不要用真实 NAI Token，不要连接 Manga。

---

## 0. 本轮已经做了什么 / 没做什么

已做：

- 按 Baseline v0 读代码、测试、决策，而不是从零设计。
- A/B 两份独立视角报告。
- 综合成 Candidate v1：KEEP / MODIFY / ADD / REJECT / UNKNOWN + E0–E4。
- 为证据不足项写了 V-* 验证方案。
- **零生产代码修改。**

没做：

- 没有跑 Adversarial Review（这是你的工作）。
- 没有实施 LibraryWriter / sidecar / snapshot 复用。
- 没有 10k Windows bench，没有付费真机。
- 没有把 Candidate 升级成 Baseline v1。
- 没有重评 `CAPABILITY_MATRIX.md` 的产品木桶分数。

若你发现 A/B 为了“写完”而收敛，视为缺陷，不是成绩。

---

## 1. 请优先攻击的结论

按杀伤力排序。每条都请给出**可执行反例**（测试名、夹具、或 prototype 步骤）。打不穿就写 KEEP 并说明为什么。

### A1. LibraryWriter 是必要边界，还是空 facade？

Candidate：D19 MODIFY，D20 UNKNOWN。

攻击：

- `upsert_local_work` 与 Pixiv `_persist` 的事务、多页、quota、dirty-flag 是否本质不可合并。若合并会拉长“先写盘后提交”的崩溃窗口，则 D19 应降为 REJECT 或只做字段对齐（D18）。
- 守卫测试“Provider 不得 `conn.execute`”会不会误伤 `db_crawler_writes`、maintenance、index——那些本来就该写库。
- 反例建议：列出所有当前 `INSERT INTO works` 调用点，看 writer 覆盖率是否 <50%。覆盖率低则“统一写出”是假边界。

### A2. RemoteAssetRef 会不会打裂 `WorkRef`？

Candidate：D14 ADD，且声称不换存储。

攻击：

- `favorites` / `production_queue` / 换角色队列键 `gallery_id:work_id:page_index` 若开始接受非数字 `remote_id`，`WorkRef.parse` 的 `isdecimal` 会炸。
- `aitag-online` 已在 `SELECTION_ONLY_GALLERY_IDS`。再加类型是否重复。
- 反例：一个 AITag id 不是正整数字符串时，`WorkRef.parse` 与 `RemoteAssetRef` 双轨，Butler 工具只认前者 → 静默丢收藏。
- 若你证明现有 `WorkRef` + selection-only gallery 已够，D14 应 REJECT，只保留 D15 投影。

### A3. lifecycle 投影会不会变成隐式状态机，进而倒逼改 schema？

Candidate：D15 ADD，先不加列。

攻击：

- `preview_downloaded=1` 但原页 `downloaded=0`（thumbnail_only）应算 materialized 还是 cached？分错会让“Add to My Library”重复下载或拒绝对已有预览做换角色。
- 换角色 `extract_chars` 需要 `ai_json`。仅远程引用 / 仅缩略图的资产若被投影成 materialized，批量换角色会产出空槽或错误 skip。
- 反例：Pixiv `thumbnail_only_pages=True` 的夹具 + `prepare_work_draft`。

### A4. lineage 字段会不会改变 generated 分组 API？

Candidate：D16/D17 ADD，声称旧图兼容。

攻击：

- `_group_key()` 在 site 用裸 `work_id`，非 site 用 `gallery:` / `run:`。`parent_generated_stem` 若被错误用于分组，侧栏会拆组或并组。
- `recipe_fingerprint` 若包含 `seed`、时间戳、或未冻结的 draft，预览与 run 指纹不一致，用户会以为“配方丢了”。
- 反例：同一 queue 项 preview 两次、run 一次，指纹应稳定；`generation_series_id` 分组不得变。
- 冻结 comment 已存在。若 fingerprint 只是它的 sha256，D17 可能是重复基础设施（简化机会，不是必须 ADD）。

### A5. 三库 snapshot 复用的锁范围

Candidate：D23 ADD。

攻击：

- `GallerySnapshotManager.create` 会停 crawler、持 maintenance lock。参数化到 Codex 时若仍调 `_auto_stop_crawler`，会误停 Pixiv。
- restore 交换目录时若 `images_dir` 算错，可能扫到 `data/images`（site）。
- 反例：并行 site crawler heartbeat 仍更新的同时 restore Codex，site `aitag.db` mtime/inode 必须不变。
- zip 进用户原图是否违反“snapshot 不含凭据”合同（`test_gallery_snapshot.py` 已锁 site）。Codex 若含本地路径元数据，restore 是否泄漏到另一台机器。

### A6. “远程失败不拖垮本地”是否被高估？

Candidate / Optimizer：C13 KEEP，认为已隔离。

攻击：

- `GET /data/images/{path}` 对 site 仍有 CDN fallback 路径（需核对 `cdn_fallback` 在 catalog 为 False，但 `routes/gallery.py` serve_image 是否仍尝试 CDN）。
- AITag 超时是否拖住同一 worker/事件循环，导致本地 `/api/ai_works_search` 饥饿。
- `gallery_guard.main_gallery_empty` 与远程失败的交叉：空库 + 远程发现失败是否误伤本地 drop。
- 反例：给 AitagClient 一个挂起 30s 的 handler，并发打本地 search，测 p95。这是可做的故障注入，现有 `test_fault_injection.py` **没有**覆盖。

### A7. 木桶评分是否在偷换概念？

Barrel 把 C12 标 2.0* 表示测量缺失，同时说搜索形状约 7.5。

攻击：

- Reviewer 应禁止任何“补完 A–D 后架构变强”的叙述在没有 E3 时提高产品木桶。
- `post.pipeline=6.0` 与 `assist.proactive_events=6.0` 仍是产品木桶底。Candidate 承认不提高它们。请确认正文没有偷运“架构轮已补齐短板”。
- 若 A/B 把 Protected Strength 的换角色写成 8.0 却无付费真机，应打回：合同 E2 ≠ 真机 E3。

### A8. Best-of-Breed 是否局部最优 / 光环效应？

攻击：

- Hydrus URL≠file 对 **Pixiv 已物化库**价值有限；真正缺口在 AITag 收藏。若 AITag 不是用户主路径，C2 高优先级可能错。
- Immich `isExternal` 来自照片库，和 NAI 工作室的“付费生成派生”不是同一问题。用它论证 D14 可能是类比滥用。
- gallery-dl 消息协议对 QQ 文件夹源是过度建模。
- 请检查 B 报告是否因为读了对方源码就提高了“必须造 Adapter”的紧迫性（E0）。

### A9. 换角色非 site 质量分裂

Optimizer 记录：Butler 对非 site + transform 会拒绝或降级。

攻击：

- Candidate 的 Online → Materialize → Transform 闭环若鼓励用户把 AITag/Codex 图推进批量换角色，会撞上“只有 site v4 槽才有质量”的现有限制。
- 这不是新 bug，但是 **闭环叙事与现有实现矛盾**。要么 Candidate 写明“第一波闭环只保证 site + 已物化 v4”，要么承认闭环是 E0 产品故事。
- 反例：codex drop 的 NAI PNG → batch/preview。看 `extract_chars` 是否有槽。若经常无槽，D-019 UX 目标被高估。

### A10. `work_lite` 失效是否治标？

攻击：

- 还有哪些读缓存：`generated_gallery._SOURCE_CACHE` 300s、`cached_scope_total`、group_index。只修 work_lite 会留下更可见的脏读。
- 失效集合一旦扩大，是否出现“每次 drop 清过多缓存”的性能回退（E0，需 V-CACHE）。
- 若脏读在 UI 上不可见，D21 可能是过度工程。

### A11. 未验证假设清单（请逐条保持 UNKNOWN 或证伪）

这些在 Candidate §7 / Optimizer §7。你不得把它们写成已决：

1. 旗标够不够三态。  
2. Pixiv 迁 writer 的崩溃窗口。  
3. 10k p95。  
4. 用户要死链提示还是快照。  
5. fingerprint 稳定性。  
6. Codex/QQ zip 体积。  
7. 能否删 `prompt_fts`。  
8. `gallery_cache` 无上限是否会在大详情页爆内存。  
9. similar 是否已分桶。  
10. 远程收藏是否真是高价值路径（无 E4）。

---

## 2. 请明确 KEEP 的对象（打不穿就不要改口）

若无新反例，下列应保持 KEEP：

- Baseline v0 四层本身
- 批量换角色 HTTP/身份/付费/250/模块隔离合同
- 单一 NAI 客户端与 billing_uncertain
- `WorkRef` 与搜索 JSON
- 三库 + NAI-only
- Tool Kernel / planning 隔离
- embed `local_none`
- 不上 DAG / 不上第二任务库 / 不上第二 NAI 客户端
- 不合并三库、不用 hash 替换 work_id
- 不抄 AGPL/GPL
- 不自动物化远程浏览
- TTS 不进木桶；禁止 God Agent / 钩子 / 窥屏

你的报告里应有一节 **KEEP（已尝试攻击，未破）**，避免只输出风险清单。

---

## 3. 你的交付物

写到 `docs/architecture-research/`，建议文件名：

- `ADVERSARIAL_REVIEW_ROUND_1.md`

结构建议：

1. 攻击过的结论，每条：反例 / 未破 / 证据等级  
2. Candidate 决策表应改为 REJECT 或 UNKNOWN 的 ID  
3. 仍 KEEP 的 ID  
4. 你要求补做的 V-* 或新反例测试（只设计，不实施，除非用户下一轮下令）  
5. 你认为可以进入 Baseline v1 的最小子集（可以为空；空是合法结果）

禁止：

- 新造总体架构图替代 v0
- 修改生产代码
- 把合成 bench 写成 10k
- 为了完成任务而把 UNKNOWN 收成 MODIFY
- 降低 `p1 == 0` 或删测试
- 合 main / Release / 真 Token

---

## 4. 回归与安全提醒

换角色是 Protected Strength。你的任何“更干净的资产模型”只要动摇下列之一，默认失败：

- `POST /api/plugin/char-swap/batch/preview` 不打 NAI
- `batch/run` 默认 `force_free=True`
- 付费冻结 `patched_comment`
- `billing_uncertain` → 409 / needs_review
- 跨页身份不匹配 → skipped
- `planning.py` 不 import tooling

用户旧库：任何 schema 建议必须 additive，必须能 rollback，必须先有 snapshot。

---

## 5. 本轮已知的方法学弱点（请连木桶法一起审）

A/B 已自报：

- 可能局部最优（provenance vs 换角色 HTTP）
- C12 分数易被误读
- LibraryWriter 可能过度工程
- C2+C14+C1 容易滚成大改
- 标杆光环（Hydrus / Immich / IIB / gallery-dl）

请额外检查：

- 是否忽略了 **generated gallery 与三库双宇宙** 才是比 Provider 更大的真实耦合。若你认为应先统一 generated 与 Library，必须给出不破坏换角色侧栏分组的反例方案；给不出就保持 REJECT 合并。
- 是否忽略 **闲云 / 多 token 池** 已是 Provider，却被 Acquire 讨论漏掉。生成 Provider ≠ 图源 Provider。Candidate 若把两者塞进同一 descriptor，请打断。

---

## 6. 环境与指针

| 项 | 值 |
|---|---|
| 研究分支 | `cursor/architecture-research-round1-0ce7` |
| 集成 tip 基线 | `cursor/cloud-top-tier-integration-f036` @ `11a7933` |
| `main` | 不要改 |
| 测试现状（检查点） | 1155 passed / 68 skipped；本轮未重跑全量（文档-only） |
| 下一角色 | 仅 C。不要启用 Integrator / Judge |

粘贴指令：

```text
你是 Adversarial Reviewer。阅读
docs/architecture-research/ROUND_1_HANDOFF.md
以及 candidate-v1.md、ARCHITECTURE_OPTIMIZER_ROUND_1.md、
BARREL_BENCHMARK_RESEARCHER_ROUND_1.md。
不要从零设计。不要改生产代码。
重点攻击 LibraryWriter、RemoteAssetRef vs WorkRef、
lifecycle 与 thumbnail_only、lineage 分组、
三库 snapshot 锁、远程失败隔离、换角色非 site 闭环、
以及木桶法自身。打不穿写 KEEP。打穿则降为 REJECT/UNKNOWN
并给出反例测试。不要把 Candidate 当成 Baseline v1。
```
