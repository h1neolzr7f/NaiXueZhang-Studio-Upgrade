# Nai学长工作室：Cursor Grok 自主完成计划

> Goal: 在尽量少人工干预的前提下，让 Cursor Grok 基于当前 `NaiXueZhang-Studio-Upgrade` 代码库和三轮架构研究结果，在线持续迭代，尽可能一次性完成下一代架构与产品闭环；用户最后在 Windows 本地做真实验收，再根据实测反馈修改。
>
> Base branch: `cursor/cloud-top-tier-integration-f036`
>
> Execution principle: **先修 correctness 与授权闭环，再完成 D-019 四层架构落地，再完成 Agent Interaction & Capability Control Plane；持续运行测试、故障注入、benchmark、迁移演练并自我修复。禁止 Big Bang Rewrite。禁止为了“更现代”而重写已经稳定的能力。**

---

# 0. 总指令：少干预自主执行

你是本轮的 Lead Implementation Agent。不要停留在分析报告，也不要每完成一个小步骤就等待用户确认。除非遇到以下真正阻塞，否则应自主继续：

- 需要真实 NovelAI 付费调用；
- 需要真实 Pixiv/第三方账号凭据；
- 需要 Windows 专属硬件/DPAPI/真实浏览器环境且云端无法模拟；
- 需要用户作产品取舍且没有安全的默认方案；
- 会造成不可逆用户数据破坏；
- 会涉及违反第三方授权/访问控制/平台规则的行为。

其他情况：**自己读代码、自己改、自己测、自己回滚失败方案、自己迭代，直到达到 Freeze Gate 和 Release Candidate Gate。**

不要修改 `main`。从当前基线创建独立实现分支，建议：

`cursor/autonomous-next-architecture-grok`

整个实现过程中持续维护：

- `docs/top-tier-upgrade/AUTONOMOUS_PROGRESS.md`
- `docs/top-tier-upgrade/AUTONOMOUS_DECISIONS.md`
- `docs/top-tier-upgrade/AUTONOMOUS_TEST_EVIDENCE.md`
- `docs/top-tier-upgrade/AUTONOMOUS_PENDING_WINDOWS.md`
- `docs/top-tier-upgrade/AUTONOMOUS_FINAL_REPORT.md`

这些文档是事实源，不依赖聊天上下文。

---

# 1. 必须保留的产品能力

目标不是做一个“更干净但功能更少”的新版本。稳定版现有功能目标保留率接近 **100%**。

Protected Strengths 至少包括：

- **批量换角色**：角色槽、性别、动作/场景保留、点击时冻结、preview、`force_free`、部分失败、`billing_uncertain`；
- 单一 NAI client 与现有 compile 路径；
- GenerationJobManager；
- Butler/LangGraph durable workflow；
- Tool Kernel 的无副作用交互边界；
- `WorkRef={gallery_id,work_id}` 与旧搜索 JSON 兼容；
- 三库隔离；
- AITag 在线发现；
- Pixiv/QQ/local import；
- Studio / generated gallery / post pipeline；
- FTS / duplicates / similarity；
- snapshot / restore；
- Local-first、DPAPI、path jail、会话令牌、敏感扫描；
- 付费失败不自动重试、`running→unknown`、receipt 幂等；
- 现有 UI/经典图库入口在迁移期必须继续可用。

任何结构改动如果导致上述能力退化，优先撤销该结构改动，而不是降低测试要求。

---

# 2. 最终目标架构

业务架构保持：

`Acquire → Curate → Transform → Library`

上层增加独立但正交的 Agent Interaction & Capability Control Plane：

`User → Persona/Agent → Orchestrator → Capability Gateway → Durable Workflow → Acquire/Curate/Transform/Library`

四个问题必须分开：

- 业务域回答“系统有什么能力”；
- Agent Persona 回答“谁最擅长帮用户使用这些能力”；
- Capability Gateway 回答“当前 Agent 在当前任务允许做什么”；
- Durable Workflow 回答“决定执行后如何可靠完成”。

禁止把一个 Agent 等同于一个业务模块。采集助手可以拥有有限 Library 能力，图库助手可以请求 Acquire/Transform，生成助手可以查询 Remote reference，但所有跨域能力都必须经过 Capability Gateway。

---

# 3. 第一优先级：先修三轮研究已确认的 correctness / safety

在新架构大规模迁移前，先把已确认 P1/P2 打穿并写回归锁。

## P1-A：服务端非免费 NAI 授权闭环

当前问题：前端确认不构成安全边界，compile 后 `free_eligible=false` 的请求需要服务端授权。

要求：

- compile 后判断 cost/free eligibility；
- 非免费请求必须带服务端可验证的一次性 authorization/confirmation ticket；
- ticket 绑定冻结批次 manifest、action、copies、cost-relevant payload hash；
- payload/copies/action 改变时 ticket 失效；
- ticket 重放、过期必须在 HTTP transport 前拒绝；
- Studio 继续使用现有 GenerationJobManager，不新建第二任务生命周期；
- Butler 发起可复用 Butler confirmation；
- transport 已开始后失败仍进入 `unknown` / `billing_uncertain`，不得自动重试；
- 对齐 `force_free` / `preserve_action` 等安全默认值。

必须增加反例测试。

## P1-B：Provider → Materialize 写入契约

目标：新 Provider 不需要自己知道 Library SQL。

要求：

- 建立薄、稳定、可测试的 `materialize_asset(...)` / LibraryWriter 边界；
- Provider/Crawler 不直接写 `works` / `work_images`；
- 保留 Pixiv receipts、sha256、多页和 quarantine 语义；
- 先 additive 封装，不一次性重写 Pixiv Intake；
- 对 QQ / drop / Codex 优先接入新写入边界，再迁 Pixiv；
- 加 no-direct-library-write guard 测试；
- 同一输入走旧/新路径必须能做结果 diff。

## P2-A：gallery index 500 截断

要求：

- 用 `(work_id,page_index)` 稳定 keyset continuation；
- cursor 与本页 upsert 原子提交；
- crash 后可重复但不能跳项；
- 新插入到 cursor 之前的记录最终可通过 reconciliation 补扫；
- 501/1001 等反例必须自动测试。

## P2-B：unindexed / stale 可见性

要求：

- source→index anti-join 标出 `unindexed`；
- index→source anti-join 标出 `stale`；
- reconciliation 只在明确 scope 内执行；
- 不得把“没出现在当前分页”误判为 stale 删除。

## P2-C：近重复跨桶漏检

要求：

- 当前高位单桶不能作为保证召回的候选生成；
- 对阈值 `t` 使用至少 `t+1` 不重叠 band 的 pigeonhole 候选策略，或其他具有同等召回保证的实现；
- dHash/pHash 分别保证召回；
- 先保留当前 pair 语义，不顺手改 connected-components；
- 加跨桶 Hamming distance=1/2 等确定性反例。

## P2-D：Remote identity 必须 source-qualified

不能只依赖 opaque remote ID。Remote reference 至少包含：

`provider_id + remote_id + source_url/source_key + identity_version`

继续保留 `WorkRef` 作为本地公共 ID，不破坏旧 API。

---

# 4. 第二优先级：把 D-019 真正落成可用闭环

## 4.1 Remote / Cached / Materialized

不要先把它做成复杂互斥状态机。优先采用“事实 + 投影”设计：

- Remote：只有 provider-qualified ref / metadata；
- Cached：存在可淘汰缓存，但未成为用户永久资产；
- Materialized：Library 中存在持久资产记录/文件。

如果实现过程中证明持久化 lifecycle 字段显著简化查询且不会漂移，可以采用 additive 字段；否则以事实派生。必须用测试证明选择。

收藏与下载分开：

- Favorite 可以是 Remote reference；
- Add to My Library / Download 才 materialize；
- 远程来源失效时收藏仍应可显示已有 snapshot/metadata，并明确 unavailable；
- 缓存 LRU/清理不得删除 Materialized 资产。

## 4.2 Online / My Library UX

用户在同一视觉体系中浏览，但清晰区分 Online 与 My Library。

至少支持：

- Online 搜索/浏览；
- Remote card 状态；
- Favorite；
- Add to My Library；
- selection set；
- 选中 Remote assets 后只 materialize 当前处理所需条目；
- 进入批量换角色/生成/后处理；
- 结果自动进入本地 Library；
- provenance 可追踪。

不要为了这个版本立即做多 Provider 统一混排 Ranking。可以采用双 section / provider tabs / local+remote 分区，先保证正确和清晰。

## 4.3 Provenance / Lineage

先做最小可查询/可复现的 lineage，不上通用 DAG。

至少统一：

- provider/source；
- remote id/source URL；
- source sha256；
- acquired_at；
- author/rights/license（可获得时）；
- parent asset/work ref；
- recipe/transform summary；
- generated sidecar 的稳定 `recipe_fingerprint` / `parent_generated_stem` / `transform_summary` 或等价字段。

批量换角色输出必须能追到源图和本次 frozen recipe。

---

# 5. 第三优先级：多专业助手 + Capability Control Plane

目标不是增加几个换皮聊天框，而是统一 Agent 权限与跨域执行。

建议默认 Persona：

- 采集助手：Acquire 为主；
- 图库助手：Curate/Library 为主；
- 生成助手：Transform/NAI 为主；
- 客服助手：Read/Explain/Diagnose 为主；
- Orchestrator：隐藏或弱可见，只负责理解、拆解、路由、授权协调和 workflow tracking，不成为超级管理员。

## 5.1 Capability Registry

权限对象是 Capability，不是 Persona。

示例：

- `provider.search`
- `provider.fetch`
- `crawler.start`
- `crawler.stop`
- `asset.preview`
- `asset.materialize`
- `library.search`
- `library.collection.add`
- `library.delete`
- `transform.character_replace`
- `nai.generate`
- `nai.generate_paid`
- `post.upscale`
- `publish.pixiv`

每个 Capability 具备：

- risk class；
- GUI visibility；
- agent-callable；
- confirmation rule；
- scope limits；
- audit requirement；
- durable vs interactive execution mode。

## 5.2 四级权限决策

统一：

- `ALLOW`
- `CONFIRM`
- `DELEGATE`
- `DENY`

Persona 只决定默认能力集合。

### Primary

该助手默认擅长、低风险时直接调用。

### Adjacent

为了完成任务可有限跨域。

### Restricted

需用户确认、服务端票据或 delegation。

### Deny

无论 LLM 如何请求都禁止。

## 5.3 Typed Handoff

助手间禁止靠自由文本作为唯一交接协议。

使用 typed handoff，例如：

`SelectionSet + UserIntent + Provenance + Scope + GrantedCapabilities + WorkflowRef`

自然语言可以用于 UI 说明，但底层执行必须用结构化对象。

## 5.4 Delegation Token

跨域权限采用短生命周期、任务级 delegation，不给永久大权限。

Token 至少绑定：

- requester agent；
- target capability；
- workflow/task id；
- source/provider scope；
- asset/collection scope；
- quantity/size/cost ceiling；
- expiry；
- one-time/replay rules。

完成任务后自动失效。

## 5.5 Agent-only Capability

允许存在 GUI 不直接提供按钮、但 Agent 可以在权限/确认范围内调用的高级能力，例如高级采集 workflow。

这不是“隐藏后门”。Capability Registry、权限规则、scope、audit 必须完整存在。

大规模采集必须尊重来源授权/平台规则，不绕过访问控制。对高规模请求先形成 AcquisitionPlan，包含 estimated_items/size/scope/filter/destination，然后按风险规则确认。

## 5.6 Orchestrator

只做：

`Understand → Plan → Route → Request Delegation → Track Workflow → Present Result`

禁止：

- 直接拥有所有执行权限；
- 绕过 Capability Gateway；
- 自己重实现 crawler/generator/library SQL；
- 把多个 durable task 简化成无持久化 LLM 对话。

---

# 6. 第四优先级：现有功能充分复用

新架构必须“收编”现有能力：

- crawler → Acquire Adapter；
- AITag → Online Provider；
- FTS / duplicate / similarity / favorite → Curate；
- batch character replace → Transform Protected Strength；
- NAI / Studio → Transform；
- post_pipeline → Transform；
- gallery / generated gallery → Library UI；
- Butler/LangGraph → Durable Workflow；
- Tool Kernel → Capability execution kernel 的已有基础；
- snapshot → migration/backup recovery；
- existing assistants → 逐步迁为 Persona，而不是删除重写。

如果能通过 facade/adapter 复用，就不要重写。

---

# 7. 自主迭代循环

每完成一个里程碑，自动执行：

1. 运行相关最小测试；
2. 运行全量 Linux 可执行测试；
3. `product_quality_gate`；
4. sensitive scan；
5. compile/static checks；
6. 对新增边界做反例测试；
7. 必要时 benchmark / fault injection；
8. 如果失败，先定位回归，再修复，不降低测试门槛；
9. 更新 AUTONOMOUS_PROGRESS / DECISIONS / TEST_EVIDENCE；
10. 继续下一里程碑。

不要在每次小失败后停下来问用户。

---

# 8. 必须做的故障注入

云端能做的尽量做到 E3：

- provider 429 / 5xx / timeout；
- provider schema/API 返回异常；
- network unavailable 时 Local Library 正常；
- cache eviction 不影响 materialized；
- DB/文件写入部分成功；
- SQLite lock；
- migration 中断；
- index crash / continuation；
- paid authorization replay/expiry/hash mismatch；
- generation transport started 后异常 → unknown；
- batch character replace 部分成功/失败；
- agent delegation expiry/replay/scope violation；
- assistant 尝试调用 DENY capability；
- provider 尝试直接写 Library；
- orchestrator 尝试绕过 Gateway。

---

# 9. 性能目标与云端验证

先 correctness 后性能。

至少构造：

- 10k synthetic library；
- 100k synthetic metadata/index 数据；
- 搜索、incremental index、similarity、startup、cache operations 的基准；
- 记录 p50/p95/max 和内存占用趋势；
- 不能把 Linux synthetic 结果冒充 Windows E3。

真实 Windows 大库、DPAPI、真实 Browser、真实 NAI/Pixiv 统一写入 `AUTONOMOUS_PENDING_WINDOWS.md`。

---

# 10. UI / 产品成品目标

不要只完成后端架构。

在线版本至少要形成用户可理解的成品体验：

- Online 与 My Library 清晰但风格统一；
- Remote/Favorite/Cached/Local 状态可理解；
- Add to My Library 明确；
- 现有批量换角色入口保留并更顺滑；
- 采集/图库/生成/客服助手具备明确身份与职责；
- 用户可以找任意助手说跨域任务，不被“找错助手”阻塞；
- 跨域操作在 UI 上能显示正在由哪个 workflow/assistant 处理；
- 付费、删除、大规模采集等高风险动作有明确确认；
- 普通用户不需要理解 Provider/Materialization/Capability Token 等内部术语。

保持经典入口兼容，除非有新入口可以并行存在并通过回归验证。

---

# 11. Architecture Freeze Gate

只有满足以下条件才认为架构阶段完成：

- 现有稳定功能保留率接近 100%；
- 批量换角色不退化；
- 非免费 NAI 服务端授权闭环 E2/E3；
- gallery index correctness 缺陷有回归锁；
- Provider 不直接写 Library 的边界有测试锁；
- Remote/Local/Materialize 语义稳定；
- Provider 单点失败不拖垮 Local Library；
- provenance/lineage 能覆盖关键用户路径；
- Agent Capability Gateway 无明显绕过路径；
- delegation replay/scope/expiry 有反例测试；
- 没有未解决 P0/P1；
- 核心高价值能力无明显 <8.5 木桶；
- 连续两轮 self-review 只产生局部修正，不再改变总架构。

---

# 12. Release Candidate Gate

在线云端完成后，不直接宣称正式发布。产出一个可交给用户 Windows 本地验证的 RC。

必须：

- 全量云端测试通过；
- quality gate p0/p1/p2 为 0 或任何非 0 都有明确阻塞说明；
- sensitive scan clean；
- migration/rollback 文档齐全；
- 旧库兼容测试；
- 不包含用户数据/token/cookie；
- 不执行真实付费 NAI；
- 不执行真实账号敏感验证；
- 生成 Windows 本地验证 checklist；
- 生成 `AUTONOMOUS_FINAL_REPORT.md`：已完成 / 未完成 / UNKNOWN / Windows 必测 / 回滚方式 / known risks。

---

# 13. 本地最终验收清单（留给用户）

云端必须最终把以下内容整理成傻瓜式验证步骤：

- 一键启动；
- 旧图库升级；
- 旧批量换角色；
- 新 Online → Favorite → Add to My Library；
- Online → selection → 批量换角色 → 生成 → 入库；
- Provider 离线时本地图库；
- DPAPI token round-trip；
- 真实 10k/100k 图库性能；
- 真实 NAI free 与 paid-confirm 流程（用户决定是否执行付费）；
- Pixiv/QQ/local import；
- 采集助手 / 图库助手 / 生成助手 / 客服助手；
- 跨助手 delegation；
- crash/restart 恢复；
- snapshot/rollback。

用户线下测试后只需反馈具体失败/不满意点，再进行下一轮局部修正。

---

# 14. 禁止事项

- 不 merge `main`；
- 不降低测试门槛换取全绿；
- 不删 Protected Strength；
- 不做 Big Bang Rewrite；
- 不为了“统一”引入第二套 durable workflow；
- 不为了“现代”引入微服务；
- 不先做大一统 DAG；
- 不先做中央 Cache Manager；
- 不先做统一多 Provider Ranking；
- 不让 Orchestrator 成为 God Agent；
- 不让 Persona 直接等于底层权限；
- 不把 GUI 不可见 capability 做成无审计后门；
- 不绕过第三方访问控制，不把第三方完整数据库未经授权打包/镜像；
- 不做真实付费 NAI 调用；
- 不把 synthetic Linux benchmark 宣称为 Windows 真实结论。

---

# 15. 给 Cursor Grok 的一键启动指令

用户在 Cursor Cloud / Long-running Agent 中只需要发送：

> 阅读并执行 `docs/top-tier-upgrade/CURSOR_GROK_AUTONOMOUS_FINISH_PLAN.md`。从 `cursor/cloud-top-tier-integration-f036` 创建独立实现分支，作为 Lead Implementation Agent 自主完成任务。不要停在分析阶段；按计划实现、测试、故障注入、benchmark、修复回归、继续迭代，直到达到 Architecture Freeze Gate 和云端 Release Candidate Gate。不要修改 main，不做真实付费 NovelAI/Pixiv 敏感调用。除非遇到计划中定义的真正阻塞，否则不要等待用户确认。最终提交完整实现、测试证据、Windows 待验清单和 `AUTONOMOUS_FINAL_REPORT.md`，让用户线下只需要安装/运行/测试并反馈问题。
