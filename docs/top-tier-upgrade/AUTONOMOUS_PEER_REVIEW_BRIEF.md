# 给审查模型的对账简报

> 读者：另一个模型 / 审查 Agent。不要信聊天记录，不要信本文件的“已完成”措辞。用代码和测试打脸。
>
> 作者：Cursor Grok 实现轮（Lead）。立场是实现者，有自证偏差。
>
> 仓库：`h1neolzr7f/NaiXueZhang-Studio-Upgrade`  
> 审查分支：`cursor/autonomous-next-architecture-96fe`  
> 证据提交：`d2ddfc1a15b626241c3f4991d01a5ee49914bb10`（以 `git rev-parse HEAD` 为准）  
> 计划基线：`cursor/cloud-top-tier-integration-f036` @ `0e6564bc39c20a48df9dac7845ccac57a2156cd8`  
> Draft PR：https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/12  
> 基线 PR（f036，不要当成本轮实现）：https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/3
>
> **禁止合 `main`。禁止发 Release。禁止真实付费 NAI / 真实 Pixiv 登录。**

---

## 0. 你要回答的唯一问题

实现轮声称：**Linux Cloud RC 已满足** `docs/top-tier-upgrade/AUTONOMOUS_SELF_TEST_LOOP.md` §9。

你的任务是判定下面三选一，并给出可复现证据：

1. **同意 Cloud RC**：门禁和关键边界经得起攻击；残留只依赖 Windows / 真实账号 / 真实付费。
2. **不同意，有 P0/P1**：写出路径、文件、复现步骤、应补的测试。
3. **不同意，声称过满**：实现存在，但证据等级不够，或把 stub/synthetic 写成了产品完成。

不要写“整体不错”。不要只复述本文件。发现漏洞时优先：`写测试 → 指出应修位置`，不要只写感想。

---

## 1. 先读这些（按顺序）

计划与门禁（审查标准，高于实现轮自述）：

1. `docs/top-tier-upgrade/CURSOR_GROK_AUTONOMOUS_FINISH_PLAN.md`
2. `docs/top-tier-upgrade/AUTONOMOUS_SELF_TEST_LOOP.md`（冲突时以此为准）

实现轮自述（有偏差，当指控清单）：

3. `docs/top-tier-upgrade/AUTONOMOUS_FINAL_REPORT.md`
4. `docs/top-tier-upgrade/AUTONOMOUS_TEST_EVIDENCE.md`
5. `docs/top-tier-upgrade/AUTONOMOUS_DECISIONS.md`
6. `docs/top-tier-upgrade/AUTONOMOUS_PENDING_WINDOWS.md`

然后直接读代码，不要再读更多战略文档。

---

## 2. 实现轮声称落地了什么

| ID | 声称 | 主代码 | 主测试 |
|---|---|---|---|
| P1-A | 非免费 NAI 必须带一次性服务端 ticket；compile 后、token pick / HTTP 前拒绝 replay / expiry / hash mismatch | `nai_authorization.py` `nai_batch.py` `nai/generate.py` `routes/nai.py` `routes/char_swap.py` `butler/execute.py` `butler/batch_ops.py` `butler/workflow_executors.py` | `tests/test_nai_authorization.py` `tests/test_char_swap_http_contract.py` |
| P1-B | QQ/drop/Codex/synthetic 走 `materialize_asset`；Provider 模块不得 `INSERT INTO works/work_images` | `library_writer.py` `scripts/gallery_import_common.py` | `tests/test_library_writer_and_remote.py` |
| P2-A | `(work_id,page_index)` keyset；501/1001 不丢不跳 | `gallery_index.py` `run_incremental` | `tests/test_gallery_index_continuation.py` |
| P2-B | source↔index anti-join；不得把“不在本页 500”当 stale | `list_unindexed` `list_stale` `reconcile_index` | 同上 |
| P2-C | dHash/pHash 各 `t+1` 不重叠 band；跨桶 Hamming 1/2 能召回 | `hash_bands` `find_near_duplicates` | 同上 + `tests/test_mutation_and_faults.py` |
| P2-D | `RemoteAssetRef = provider + remote_id + source_url/source_key + identity_version`；`WorkRef` 不变 | `remote_asset.py` | `tests/test_library_writer_and_remote.py` |
| D-019 | Remote/Cached/Materialized 是事实不是互斥状态机；收藏≠入库；cache 不得删 materialized | `library_lifecycle.py` `online_library.py` `web/online-discover.js` | `tests/test_online_library_e2e.py` |
| Cap | Gateway 四级决策；Orchestrator 不能执行；delegation replay/expiry/scope | `capability/*` `routes/online.py` | `tests/test_capability_gateway.py` |

产品入口声称：

- 经典 `/` 有「在线发现」，**没有**第 9 个主导航。
- Studio / 换角 / Butler 付费路径先 authorize 再 generate。
- React `frontend/src/pages/GalleryPage.tsx` **不是** `/` 产品壳。`/app` 仍重定向到经典页。

---

## 3. 实现轮自己承认的洞（先核实是否属实，再找没写出来的）

实现轮说云端已修：

1. 授权曾排在 token 检查之后。
2. Butler ticket 的 action 必须是 `studio_generate`。
3. 发 ticket 的 targets 必须与 `build_studio_targets` 一致。
4. 付费部分重试曾用 subset compile hash 对完整 job hash → 合法重试 403。
5. `_paid_authorized=True` 可绕过 ticket；现应忽略调用方该参数，只信落盘 job。
6. 换角 UI 曾不发 ticket。
7. `batch.js` 超 925 行预算，授权逻辑抽到 `api.js`。
8. Online 做在 React 图库页上，但 `/` 根本不挂该页。

实现轮主动降级、不要被忽悠成“已完成”：

- Pixiv intake **仍直写** Library SQL（`pixiv_nai_intake.py` 在 allow-list）。
- 站点爬虫 SQL 仍在 `db.py` / `db_crawler_writes.py`。
- Ticket 密钥和已消费 nonce **只在进程内存**；重启作废未用票。
- Online 收藏对 synthetic provider 是**进程内存**，重启清空。
- 10k/100k 是 Linux 合成元数据，**不是** Windows 真库。
- E2E 的 Transform 段是 `preview_only` 换角，不是真实付费出图。
- `frontend/src/pages/GalleryPage.tsx` 对 `/` 用户不可见。

---

## 4. 必须攻击的路径（按危害）

每条都要：读代码 → 想绕过 → 看测试是否真能抓住。能绕就写 PoC 级复现（测试或调用序列），不要只写“可能有问题”。

### 4.1 付费 / 重复扣费

- `POST /api/nai/authorize` 不经 UI 确认就能发票。本地应用是否可接受？有没有数量/费用上限？
- `generate_image(..., paid_authorized=True)` 是否有 HTTP 或非 job 路径能直接传入？
- `start_batch(_paid_authorized=True)` 现在是否真的被忽略？`retry_batch` 改 disk 上的 `_request.targets` / fingerprints 能否把更贵的 payload 洗成已授权？
- ticket 绑定的 `cost_relevant_view` 是否漏了会改变计费的字段（model / smea / vibe / 尺寸）？
- `force_free=True` 但有 image/mask/reference 时，是否仍 `requires_ticket`？UI 是否在 `force_free` 勾选时仍确认？
- transport 已开始后的 5xx / timeout 是否仍进 `unknown` / `billing_uncertain` 且不能自动重试？
- Butler 确认后发的 ticket action 是否与 `start_studio_generate` / `start_batch` 实际 action 一致？

### 4.2 数据一致性 / 索引

- `run_incremental` 的 cursor 与 upsert 是否同一 `commit`？崩溃是否会跳项？
- `reconcile_index(work_ids=[...])` 会不会误删 scope 外 stale？会不会把未扫页当 stale？
- 新插入 `work_id` 小于当前 cursor 时，是否只能靠 reconciliation 补扫？有没有自动补扫？
- `hash_bands` 对 `t=4` 是否真是 5 个不重叠 band？余数分配会不会让 Hamming≤t 仍漏召回？
- `find_near_duplicates` 的 pair 语义有没有被改成连通分量？

### 4.3 Library 写入

- no-direct-write guard 只扫了白名单文件列表。还有哪些模块 `INSERT INTO works`？
- `materialize_asset` 文件成功、DB 失败（或反过来）会不会留下孤儿？
- drop / QQ 路径是否仍有第二条 SQL 写入？
- `RemoteAssetRef` 缺 `source_url` 是否仍能创建？跨 provider 相同 `remote_id` 会不会撞。

### 4.4 Online / UX

- `web/online-discover.js` 是否用 `ApiClient`（质量门禁禁裸 fetch）？
- 在线搜索失败时，是否把本地图库标成不可用？
- 「收藏」是否写文件？「加入我的图库」是否只 materialize 当前这一条？
- 主导航是否仍正好 8 项？`tests/test_site_nav_ui.py` 是否仍绿？
- React `GalleryPage` 与经典面板是否两套语义，用户会走哪套？

### 4.5 Capability

- Orchestrator `route()` 只做关键词，会不会对「删除」返回 DENY 却仍让下游执行？
- `CapabilityGateway` 在 `store is None` 时走模块级 `_STORE`，HTTP `/api/capability/decide` 用的是哪一个？
- Agent-only `acquire.plan` 有没有审计/确认？会不会变成无按钮后门？
- Persona 默认表是否把 `nai.generate_paid` 给了不该给的助手？

### 4.6 回归 / 木桶

- 是否引入第二套 NAI client 或第二套任务生命周期？
- `planning.py` 是否 import 了 `butler.tooling`？
- `db.py` 是否又超过 1000 行？
- `web/plugins/char-swap/batch.js` 是否又超过 925 行？
- `/api/ai_works_search` JSON 是否仍兼容旧 `WorkRef`？

---

## 5. 门禁：实现轮数字 vs 你必须重跑

实现轮记录（**你要重跑，不要抄**）：

```text
pytest -q --ignore=tests/test_pixiv_selector_probe.py
# 声称 ×2：1202 passed, 68 skipped, 127 subtests

python3 scripts/product_quality_gate.py --json
# 声称 ×2：p0=p1=p2=0

python3 scripts/scan_sensitive.py --git-candidates --content-only
python3 -m compileall -q -x "runtime|\.venv|node_modules|data" .
```

最小攻击套件（先跑这些再决定要不要全量）：

```text
python3 -m pytest -q \
  tests/test_nai_authorization.py \
  tests/test_char_swap_http_contract.py \
  tests/test_gallery_index_continuation.py \
  tests/test_library_writer_and_remote.py \
  tests/test_capability_gateway.py \
  tests/test_online_library_e2e.py \
  tests/test_mutation_and_faults.py \
  tests/test_generation_jobs.py \
  tests/test_site_nav_ui.py \
  tests/test_workspace_stack.py
```

变异有效性：实现轮是**手工改源码再恢复**，仓库里没有可重复的 mutation harness。你应自己再做至少：

1. 去掉 `nai/generate.py` 的 `authorization_required` 早退 → 对应测试必须红  
2. `start_batch` 跳过 `authorize_start_batch` → `test_missing_ticket_is_rejected_before_enqueue` 必须红  
3. `hash_bands` 的 `count = 1` → 跨桶测试必须红  
4. `if False and after is not None` → `test_501_first_page_is_truncated_and_stable` 必须红（不要用 1001 循环测这个，会挂死）  
5. 允许 delegation replay → gateway 测试必须红  

做完必须 `git checkout --` 恢复。不要把变异提交上去。

---

## 6. Cloud RC 清单（逐条判真/假/证据不足）

对照 `AUTONOMOUS_SELF_TEST_LOOP.md` §9，填表：

| 条件 | 实现轮说法 | 你的判定 | 证据 |
|---|---|---|---|
| 全量 pytest ×2 | 1202/68 ×2 | | |
| quality gate ×2 | 全 0 ×2 | | |
| sensitive scan | clean | | |
| P1/P2 各有反例测试 | 有新测试文件 | | |
| 安全测试 mutation 有效 | 7/7 手工 RED | | |
| Online→Materialize→Transform→Library E2E | `test_online_library_e2e` + preview_only | | |
| delegation 四级反例 | gateway 测试 | | |
| provider outage 本地库仍可用 | E2E + faults | | |
| 501/1001 continuation | 有 | | |
| unindexed/stale | 有 | | |
| 跨桶近重复 | 有 | | |
| 付费 ticket 在 transport 前拒绝 | 有 | | |
| 批量换角 Protected Strength | 声称 EXTENDED 且回归绿 | | |
| migration/rollback 云端可模拟 | 指向已有 snapshot/schema 测试 | | |
| 10k 正确 / 100k 基准 | soak 文件；100k 只是 SELECT | | |
| 无已知 P0/P1 | 自述 | | |
| 残留 P2 只因外部环境 | 见 FINAL_REPORT | | |
| Matrix 无未验证 AT-RISK | 自述无 | | |
| 两轮自找 Bug 无新架构洞 | 自述 | | |

**特别盯：** “完整 Online → Transform → Library” 是否被 preview_only 缩水；“migration rehearsal” 是否只是旧测试挂名。

---

## 7. 审查输出格式（请严格按此写）

```markdown
# 审查结论
判定：同意 Cloud RC / 不同意（P0/P1） / 不同意（声称过满）
一句话：

# 证实成立的声称
- …

# 打穿或证据不足
- [P0|P1|P2|声称过满] 标题
  路径：
  文件：
  复现：
  现有测试为何没抓住：
  建议修复：

# 门禁复跑
pytest：
quality gate：
敏感扫描：
你做的变异：

# 不要让用户去测的普通漏洞
- …

# 可以留给 Windows 的
- …
```

语言：简体中文。代码、路径、命令用英文原样。

---

## 8. 不要做的事

- 不要合 `main`，不要改本审查简报来“帮实现轮圆谎”。
- 不要为了全绿删测试或放宽 `p1 == 0`。
- 不要跑真实付费 NAI / 真实 Pixiv。
- 不要把 Linux synthetic 写成 Windows 10k/100k。
- 不要重做 Big Bang Rewrite。能指出局部修复就指出局部修复。
- 不要审查 `main`。`main` 没有这些计划文档，也没有本轮实现。

---

## 9. 给人类的一句话

实现轮认为：云端能发现的付费绕过、漏索引、直写 Library、跨桶漏检、换角无票，已经打过并锁进测试；你只需要看 Windows 和真账号。  
审查轮的工作是：**证明这句话是真的，或者把它打假。**
