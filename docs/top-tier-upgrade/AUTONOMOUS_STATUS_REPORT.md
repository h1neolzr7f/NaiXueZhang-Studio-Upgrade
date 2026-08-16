# 当前状态报告

日期：2026-08-16  
读者：dick（产品方）  
作者：实现轮（已接受同行审查打穿）  
分支：`cursor/autonomous-next-architecture-96fe`  
HEAD：`8ab7ffdba014124a154c6b9a9a1223f1a57cb3ed`  
Draft PR：https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/12  
基线：`cursor/cloud-top-tier-integration-f036` @ `0e6564b`  
**不要合 `main`。不要发 Release。不要在云端跑真实付费 NAI / 真实 Pixiv。**

---

## 一句话

上一轮 Cloud RC 被打穿是对的；审查里的 P0/P1 已在 Linux 修完并再攻击。现在可以认为 **Linux 审查项已闭环**，但仍不是 Windows 发布，也不是付费 NAI Transform 完成。

---

## 现在停在哪

| 项 | 状态 |
|---|---|
| 工作树 | 干净，已与远程同步 |
| PR | Draft #12，base=`main` |
| 产品壳 | 经典 `/` 八项主导航；`/app` 仍重定向到经典图库 |
| 付费安全 | 无票不能 generate；SMEA 不再免费；未确认不发票；retry 有 HMAC seal |
| 图库写入 | QQ/drop/Codex/synthetic 走 `materialize_asset`；DB 失败会清未被引用的新文件 |
| 索引 | keyset 续扫；结束时补扫 cursor 前插入 |
| 在线发现 | 收藏落盘；加入图库会入库；本地 derive 带 lineage |
| Capability | 决策原型，`EXECUTION_WIRED=False`，未接执行面 |
| Cloud RC（旧声称） | 已撤回 |
| Linux 审查闭环 | 是 |
| Windows / 真实账号 / 真实付费 | 未做，留给你 |

---

## 怎么走到这里

1. **实现轮**在 f036 基线上做了付费 ticket、Library writer、索引续扫、Capability 平面，并在 `7e963da` 声称 Cloud RC。
2. **另一模型审查**判定不同意：门禁全绿，但存在可复现的付费绕过、授权重用篡改、索引/入库一致性问题，声称过满。
3. **本轮**按审查项修复，补反例，做变异攻击，全量回归 ×2，撤回旧 Cloud RC 声称。

关键提交：

| Commit | 含义 |
|---|---|
| `7e963da` | 被打穿的旧证据/声称 |
| `f9a3ef4` | 修 P0/P1 与一致性洞 |
| `b6fbd3c` | 前端重建 + 资源戳 |
| `8ab7ffd` | 文档改口：撤回旧 Cloud RC，记录审查闭环 |

---

## 审查项对照

| 审查判定 | 现在 |
|---|---|
| [P0] SMEA 无票仍 `free_eligible=True`，hash 不含 SMEA | 已修。SMEA 强制付费并绑定 hash。无票/改票有测试。 |
| [P1] 未确认就能拿到有效 ticket；UI 先发票再 `confirm` | 已修。HTTP 无 `confirmed=true` 时 `ticket=""`。UI 两步：preview → 确认 → 发票。 |
| [P1] 改 `generation_jobs.json` 的 targets+fingerprints 后 retry 放行 | 已修。首次授权写 HMAC `authorization_seal`，重试先验 seal。 |
| [P1] cursor 前插入永远 `unindexed` | 已修。扫描结束做有界 anti-join 补扫。 |
| [P1] 文件成功、DB 失败留孤儿 | 已修。失败且未被引用则删新文件。 |
| [P1] 相同 provider/remote ID、不同 source 得到同一 identity | 已修。必须有 source；digest 进入 `qualified_id`。 |
| [声称过满] Transform 只是 `preview_only`；收藏内存；Capability 当完成 | 已改口并补证据。Transform 是 **free-safe 本地 derive**，不是付费 NAI。收藏落盘。Capability 标明原型。 |
| [P2] SQL 守卫/near-dup pair/quality gate 漏扫 | 已扩守卫、改 pair 语义、把 `online-discover.js` 纳入门禁。 |

这些都能在 Linux synthetic 环境回归，不需要你去复现。

---

## 门禁与攻击证据

pytest（忽略 Windows/browser 的 `test_pixiv_selector_probe.py`）：

- 连续两轮：`1211 passed, 68 skipped, 127 subtests`

quality gate：

- 连续两轮：`p0=0, p1=0, p2=0`

敏感扫描：

- `python3 scripts/scan_sensitive.py --git-candidates --content-only`：clean
- `compileall` 通过

变异（打坏应变红，恢复应变绿）：

| 变异 | 结果 |
|---|---|
| 去掉 `generate_image` 付费门 | RED |
| 跳过 ticket consume | RED |
| `hash_bands count=1` | RED |
| 忽略 keyset `after` | RED |
| 允许 delegation replay | RED |
| SMEA 仍算免费 | RED |
| 未确认就发票 | RED |
| 跳过 retry seal | RED |
| 跳过 unindexed 补扫 | RED |
| 全部恢复 | GREEN，`git diff` 为空 |

---

## Cloud RC 条件（诚实表）

| 条件 | 判定 |
|---|---|
| pytest ×2 / quality ×2 / 内容敏感扫描 | 真 |
| 审查指出的 P0/P1 有确定性反例 | 真 |
| Online → Materialize → **本地 free-safe derive** → Library + lineage | 真 |
| Online → Materialize → **付费 NAI Transform** → Library | 假（未声称） |
| 501/1001、跨桶 pair、delegation | 真 |
| unindexed 最终补扫 | 真 |
| paid ticket 覆盖 SMEA | 真 |
| 当前 schema v2 snapshot rollback rehearsal | 真 |
| 真实旧图库升级 | 假，留给 Windows |
| Capability 已接执行面 | 假，原型 |
| Matrix 无未验证 AT-RISK | 真（未验证项已标 Windows/原型） |
| 无已知审查 P0/P1 | 真 |
| 旧 Cloud RC 原话仍然成立 | 假，已撤回 |

---

## 仍然成立、且本轮没推翻的能力

- 普通付费请求在 token/transport 前拒绝 replay、expiry、hash mismatch
- `_paid_authorized=True` 不能直接绕过；`billing_uncertain/unknown` 不自动重试
- 501/1001 静态 keyset、scoped stale/unindexed anti-join
- dHash/pHash 跨桶召回（现为 pair，不是重叠 anchor group）
- delegation 四级决策及 replay/expiry/scope
- 经典 `/` 八项主导航；`online-discover.js` 用 `ApiClient`
- QQ/drop/Codex/synthetic 主路径走 `materialize_asset`

---

## 不要让用户再测的（Linux 已锁）

- SMEA 无票、未确认签票、retry 篡改抬价
- cursor 前插漏索引、DB 失败孤儿、Remote identity 冲突
- 收藏进程重启丢失（现已落盘）
- 把 Capability 当成已接线的执行面

---

## 请你只验收 Windows / 真实环境

清单在 `docs/top-tier-upgrade/AUTONOMOUS_PENDING_WINDOWS.md`。最短路径：

1. 一键启动、中文路径、DPAPI
2. 经典图库「在线发现」：收藏不落文件，加入图库后能在自选库看到
3. Studio / 换角：有底图时先确认，**确认前不应已有可用 ticket**；取消不出图
4. 用户自愿的一小批真实付费：失败重试不要求新票；`unknown` / `billing_uncertain` 仍不能自动重试
5. 真实旧图库升级后续扫；真机 10k/100k 与主观 UI

不要在 Windows 上再花时间复现 Linux 已锁的普通漏洞。

---

## 回滚

```bash
git fetch origin
git checkout cursor/cloud-top-tier-integration-f036
```

或把本分支重置到 `0e6564b`。不要合 `main`。

---

## 相关文件

- 本报告：`docs/top-tier-upgrade/AUTONOMOUS_STATUS_REPORT.md`
- 审查闭环说明：`docs/top-tier-upgrade/AUTONOMOUS_FINAL_REPORT.md`
- 测试证据：`docs/top-tier-upgrade/AUTONOMOUS_TEST_EVIDENCE.md`
- Windows 清单：`docs/top-tier-upgrade/AUTONOMOUS_PENDING_WINDOWS.md`
- 给其他模型的打假简报：`docs/top-tier-upgrade/AUTONOMOUS_PEER_REVIEW_BRIEF.md`
