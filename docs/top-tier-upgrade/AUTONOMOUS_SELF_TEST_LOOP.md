# Nai学长工作室：自主反复迭代与自测硬门禁

> This document is a mandatory companion to `CURSOR_GROK_AUTONOMOUS_FINISH_PLAN.md`.
> Priority: if the finish plan is ambiguous about when to stop, this document wins.
> Goal: **线上不是“实现一遍然后交付”，而是“实现 → 主动找错 → 修复 → 再找错 → 回归 → 再验证”，直到云端可以达到的缺陷基本被打穿，再交给用户做 Windows/真实账号/真实付费环境验收。**

---

## 1. 禁止“一遍通过就交付”

Lead Implementation Agent 不得因为：

- 全量 pytest 一次通过；
- quality gate 一次为绿；
- happy-path demo 能跑；
- UI 能打开；
- 新功能表面可用；

就宣布 Release Candidate。

自动测试只能证明已经覆盖的行为。每完成一个阶段，必须主动寻找**测试未覆盖的反例、状态组合、边界条件和跨模块回归**。

交付前至少完成多轮独立自审与再验证。

---

## 2. 强制 Red → Green → Break → Green 循环

每一个重大能力必须执行以下循环：

1. **RED / 先造反例**：在改实现前或同时增加能复现问题/约束的失败测试；
2. **GREEN / 最小修复**：修到目标测试和相关回归通过；
3. **BREAK / 主动攻击自己的实现**：换输入、换顺序、并发、崩溃、重复请求、脏数据、旧 schema、异常 provider、权限越界等方式尝试打穿；
4. **GREEN AGAIN**：将发现的新漏洞固化为回归测试并修复；
5. **FULL REGRESSION**：跑相关套件 + 全量可执行套件；
6. **EVIDENCE**：记录本轮发现、修复、未解决项和证据等级。

对于 P1、安全、付费、数据一致性、迁移、批量任务和权限边界，至少完成 **两次 BREAK 阶段**，不能只测 happy path。

---

## 3. 每个里程碑后必须开启“自找 Bug”阶段

完成一个里程碑后，不立即进入下一个里程碑。先专门用一轮时间做 Bug Hunt。

至少从以下维度攻击：

### 状态机

- 重复调用；
- 顺序错乱；
- 中途 crash；
- 重启恢复；
- stale state；
- partially committed；
- retry 后状态重复；
- unknown / billing_uncertain 是否被错误重放。

### 数据一致性

- DB 成功、文件失败；
- 文件成功、DB 失败；
- duplicate import；
- stale index；
- missing index；
- cursor 中断；
- migration 中断；
- rollback 后新旧 schema；
- remote metadata 缺失/变化；
- source URL / ID 冲突。

### 权限与 Agent

- Persona 直接调用无权限 capability；
- Adjacent capability 越 scope；
- delegation replay；
- delegation expiry；
- delegation 改 payload；
- Orchestrator 试图直接执行；
- Agent-only capability 绕过确认；
- UI 隐藏功能是否仍受服务端 Gate；
- 客服助手是否能升级为高风险执行者。

### Provider / 网络

- timeout；
- 429；
- 5xx；
- malformed JSON；
- schema 缺字段；
- duplicate remote IDs across providers；
- provider offline；
- provider 部分页失败；
- materialization 中断；
- provider 返回恶意/超长 metadata；
- cache 与 materialized 混淆。

### Transform / NAI

- batch 部分成功；
- batch 部分失败；
- transport 已发出后 timeout；
- ticket replay / expiry / hash mismatch；
- copies/action/payload 被改；
- character replace freeze 漂移；
- parent/recipe lineage 丢失；
- post-process 失败是否污染原资产；
- generation result 重复注册。

### UI / UX

- loading / empty / error / retry；
- 网络断开后 Local Library；
- remote asset unavailable；
- favorite 仍只有 reference；
- materialized 状态展示错误；
- 高风险动作确认是否清楚；
- 多助手交接是否出现“踢皮球”或重复执行；
- 用户从任意助手发起跨域任务是否能完成。

每发现一个真实问题，优先：**写可复现测试 → 修复 → 全量回归**。

---

## 4. Mutation Mindset：主动证明测试不是摆设

不要求引入重量级 mutation-testing 框架，但对关键边界必须手工做 mutation-style 检查：

- 暂时移除付费 ticket 校验，测试必须红；
- 暂时允许 Provider 直写 DB，guard 必须红；
- 暂时允许 delegation replay，测试必须红；
- 暂时把 index continuation 固定 500，501/1001 测试必须红；
- 暂时恢复单高位 hash bucket，跨桶 near-duplicate 反例必须红；
- 暂时允许 materialized cache 被 eviction，测试必须红；
- 暂时让 Butler 对 unknown 重试，测试必须红。

然后恢复正确实现并确认 GREEN。

如果关键测试无法在故意破坏实现时失败，则该测试不算有效证据，必须增强。

---

## 5. 至少三层测试

### Layer A — Contract / Unit

用于快速锁定：

- Provider contract；
- Capability decision；
- Delegation token；
- RemoteAsset identity；
- Materialize contract；
- lineage；
- paid authorization；
- index cursor；
- hash candidate generation。

### Layer B — Integration

必须覆盖跨模块闭环：

- Provider → Curate → Materialize → Library；
- Online favorite → unavailable source → local snapshot fallback；
- Remote selection → character replace → generation job → Library lineage；
- Agent → Gateway → WorkflowRequest / Durable Workflow → Result；
- Acquire Agent 跨到 Library；
- Library Agent 跨到 Transform；
- Studio Agent 有限调用 Acquire；
- service agent 只读/诊断边界。

### Layer C — End-to-End Synthetic

在云端用合成/本地 stub source 模拟真实用户：

1. 启动应用；
2. 搜索 remote provider；
3. 收藏但不下载；
4. Add to My Library；
5. 去重/搜索；
6. 发起批量换角色的 dry-run/free-safe 路径；
7. post-process；
8. 验证结果回库和 provenance；
9. 重启应用；
10. 验证任务、收藏、Library、lineage、权限状态没有漂移。

不能只依赖 API 单测而没有完整用户链路冒烟。

---

## 6. 长时间 / 重复运行测试

交付前至少做云端可行的 soak / repetition：

- 同一关键 integration test 重复运行多次，发现 flaky；
- 多批次 materialize / index / similarity；
- 多次启动/停止/重启；
- 多次创建/消费 delegation；
- 多次失败恢复；
- synthetic provider 不定期返回 429/5xx/timeout；
- 10k/100k synthetic data 下重复增量索引和搜索。

报告 flaky rate、失败次数和最终处理结果。发现不稳定不能只 rerun 到绿色，必须查原因。

---

## 7. Regression Preservation Matrix

必须建立现有能力回归矩阵，至少覆盖：

- 批量换角色；
- Studio；
- txt2img / img2img / inpaint compile；
- GenerationJobManager；
- billing_unknown；
- Butler receipt；
- Pixiv intake；
- QQ ingest；
- local drop；
- AITag online；
- FTS；
- duplicates；
- similarity；
- snapshots；
- generated gallery；
- post pipeline；
- classic Gallery UI；
- current `/app`；
- WorkRef / old search JSON；
- security gates。

每个能力标记：`UNCHANGED / ADAPTED / EXTENDED / AT-RISK`，以及对应测试。

任何 `AT-RISK` 项未有验证证据时，不能宣布 RC。

---

## 8. 多轮自审角色切换

即使只有一个 Grok Agent，也要在不同阶段切换审查视角，而不是一直以实现者心态自证正确。

至少执行：

### Pass 1 — Implementer Review

检查是否满足计划和测试。

### Pass 2 — Adversarial Reviewer

假设当前实现有错，主动寻找能够破坏数据、绕过授权、重复扣费、漏索引、越权或破坏旧功能的路径。

### Pass 3 — Maintainer Review

假设六个月后维护：检查重复抽象、dead code、临时 compatibility hack、不可解释状态和迁移债务。

### Pass 4 — User Journey Review

以普通用户视角走完整流程，检查是否需要理解内部架构才能完成任务。

每一轮发现的问题都回到 RED→GREEN 循环，不只是写在报告里。

---

## 9. 云端 RC 的严格定义

只有同时满足以下条件才允许写 `AUTONOMOUS_FINAL_REPORT.md` 并标记 Cloud RC：

- Linux 云端全量可执行测试连续至少 **2 次**通过；
- quality gate 连续至少 **2 次**为绿；
- sensitive scan 通过；
- 关键 P1/P2 每项有确定性反例测试；
- 关键安全测试通过 mutation-style 有效性检查；
- 至少一条完整 Online → Materialize → Transform → Library 合成 E2E 通过；
- Agent 跨域 delegation 的 allow/confirm/delegate/deny 反例全部通过；
- provider outage 时 Local Library 继续工作；
- index 501/1001 continuation 通过；
- unindexed/stale reconciliation 通过；
- near-duplicate 跨桶反例通过；
- paid authorization replay/expiry/hash mismatch 在 transport 前拒绝；
- batch character replace Protected Strength 回归通过；
- migration rehearsal / rollback rehearsal 通过云端可模拟部分；
- 10k synthetic correctness 通过，100k synthetic 至少完成关键索引/搜索基准或明确记录阻塞；
- 没有已知 P0/P1；
- P2 若有残留必须明确证明只依赖 Windows/真实外部环境，不能是“没时间”；
- Regression Preservation Matrix 没有未验证的 `AT-RISK`；
- 连续两轮自找 Bug 只产生局部问题，不再发现架构级或数据安全级新缺陷。

**一次全绿不等于 RC。必须达到“反复攻击后仍然稳定”。**

---

## 10. 最终交给用户的内容

用户本地首次接手时，目标不是替 Agent 做 QA，而是验证云端无法证明的真实环境：

- Windows/DPAPI；
- 安装包/启动；
- 真机 UI 与性能；
- 真实旧图库迁移；
- 用户自己的 Provider/网络环境；
- 用户主动选择时的真实 NAI/Pixiv 测试；
- 主观 UX/交互反馈。

最终报告必须明确写：

1. 云端已经主动发现并修掉了哪些 bug；
2. 做了几轮 Red→Green→Break→Green；
3. 哪些测试被 mutation-style 验证过；
4. 哪些是 E2/E3；
5. 哪些只能留给 Windows；
6. 用户拿到手后最短测试路径。

不要把普通可在 Linux/stub/synthetic 环境发现的漏洞留给用户。

---

## 一句话执行原则

> **不要把用户当测试员。在线实现之后必须自己反复攻击、复现、修复、回归、再攻击，直到云端能发现的问题基本收敛；用户线下只负责真实 Windows/账号/付费环境和主观体验验收。**
