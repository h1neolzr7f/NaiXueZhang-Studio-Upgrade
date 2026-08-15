# Nai学长工作室：多模型架构迭代优化任务书

> Status: **Architecture Optimization Brief**  
> Repository: `h1neolzr7f/NaiXueZhang-Studio-Upgrade`  
> Working branch: `cursor/cloud-top-tier-integration-f036`  
> Purpose: 让 Cursor 中多个顶级模型基于**现有成果**做定向优化、木桶对标、对抗审查、实验验证和迭代收敛，而不是从零重复设计。

## 0. 核心任务

本项目已有大量成熟功能，也已经形成下一阶段的高价值架构基线。不要让多个模型各自从零设计一套新软件，也不要用算力做架构抽奖。

工作循环：

`Baseline v0 → 定向优化 → 木桶对标 → 对抗审查 → 实验/测试 → Baseline v1 → ... → 收敛冻结`

算力优先投入争议点、短板、代码证据和验证。只有存在明确代码证据、测试证据或显著收益时，才允许推翻局部设计。

## 1. Protected Strengths / 功能保全

现有稳定功能默认全部保留，目标保留率接近 **100%**。尤其：

- **批量换角色是核心差异化能力，禁止丢失或退化**；
- 现有 NovelAI 生成、img2img/inpaint、任务队列、超分、打码、metadata 等优先复用；
- Pixiv / QQ / 本地导入、图库、FTS、相似图、重复图等继续保留；
- Butler / Tool Kernel / durable workflow 不重复造轮子；
- Local-first、付费确认、DPAPI、路径边界和用户数据安全不能退化；
- 用户旧图库必须有迁移、备份和 rollback；
- 禁止 Big Bang Rewrite；禁止为了流行框架替换稳定路径。

## 2. Architecture Baseline v0

当前主架构：

`Acquire → Curate → Transform → Library`

它是默认优化基线，不是要求每个模型重新发明。

### Acquire

所有数据来源统一归入获取层：Remote API、在线图库/数据库、Provider、Crawler、Browser/Plugin acquisition、Local Import。**爬虫只是 Acquire 的一种 Adapter。**

### Curate

负责 Search / Filter、Tag / Prompt / Artist / Character discovery、Favorites、Dedupe、Similarity、Ranking、Collections / Selection Set，以及未来可能的语义搜索和偏好排序。

### Transform

收编而不是重写现有能力：**批量换角色**、Prompt 处理、NAI 生成、img2img/inpaint、超分、打码、metadata、抠图和其他批处理。是否引入更完整 Pipeline / Recipe / DAG 必须通过实际需求和验证决定。

### Library

Library 是用户长期拥有、保存、生成和处理后的本地资产，不是互联网镜像。

候选闭环：

`Online discovery → 用户明确选择 → Materialize / Add to My Library → Transform → 结果回到 Library`

### Remote / Local

浏览远程内容不自动永久下载。需要验证 `Remote / Cached / Materialized` 三态、收藏的引用/快照策略以及离线退化体验。

### Provider

新数据源优先作为 Provider / Acquire Adapter。Provider 不直接写 Library DB，provider-specific API/Crawler 细节不泄漏到 Library/Processor。Capability、health、rate limit、timeout、retry、circuit breaker 和缓存策略按需要验证。

### Provenance / Lineage

进入本地的资产尽量保留 provider/source、remote id/source URL、author/rights/license（可获得时）、acquisition time、parent asset、recipe/transform history。服务来源追踪、可复现和批量换角色派生关系。

## 3. 重点待优化/验证的横向能力

不要默认全部都要新造系统。逐项判断收益：

1. Universal / Canonical Asset Model；
2. RemoteAssetRef vs LocalAsset vs lifecycle state；
3. Canonical Metadata / Tag / Alias / multilingual Knowledge Layer；
4. Provider capability negotiation；
5. Multi-provider Ranking；
6. Cache Manager；
7. Provenance / non-destructive lineage；
8. Transform Pipeline / Recipe；
9. Plugin capability / isolation；
10. Schema migration / backup / rollback；
11. Observability / failure taxonomy；
12. 10k / 100k / 1M assets 性能；
13. Provider outage/API change/CORS/rate limit 降级；
14. Local + Remote 联合搜索；
15. 现有功能兼容适配。

## 4. 木桶标杆法

正式方法：

**Capability-based Benchmarking + Gap Analysis + Best-of-Breed + Constraint-driven Improvement + Regression Gates**

每个能力桶记录：Capability、Current Evidence、Current Score+Confidence、User Value、Risk、Benchmark、Why Better、Mechanism to Borrow、What NOT to Borrow、Proposed Change、Validation、Regression Risk、Rollback、New Score。

规则：

- 不找一个项目整体模仿，每个能力单独找 Best-of-Breed；
- 标杆只能提高该桶标准，不能因为对方更有名就整体照搬；
- Nai学长已经更强/更适配的能力标记为 Protected Strength；
- 优先补高价值短板，不把所有 9 分桶强行磨到 10；
- 对标尽量读代码、测试、schema、failure handling，而不只看 README；
- 许可证、数据授权、Windows/local-first 适配和维护成本计入收益；
- 所有改动经过 regression gate。

Reviewer 同时审查木桶法自身：防止局部最优、评分主观、过度工程以及忽略桶间耦合。

## 5. Cursor 多模型角色：第一阶段只需三个

### A — Architecture Optimizer

在 Baseline v0 上直接优化，不从零重做。寻找错误抽象、遗漏边界、耦合、重复基础设施、未来瓶颈和可以简化的地方；同时明确哪些设计已经足够好、应该 KEEP。重大建议必须给证据、迁移风险、验证方法和 rollback。

### B — Barrel Benchmark Researcher

不重新设计总体架构。建立 Capability Matrix，对高价值短板寻找 Best-of-Breed，阅读关键代码/测试/schema，提取适合 Nai学长的机制和明确不适合的部分，给出最小高收益改动及验证方法。

### C — Adversarial Reviewer

在 A+B 形成候选改进后运行。不要再造宏大架构，专门尝试证明候选会失败：过度设计、功能退化、换角色受损、迁移风险、Provider failure、SQLite/cache、重复 workflow、插件权限、性能、不可验证假设。对合理设计明确写 KEEP。

## 6. 迭代循环

```text
Current Baseline vN
        │
   ┌────┴────┐
   ↓         ↓
Architecture   Barrel Benchmark
Optimizer       Researcher
   │             │
   └──────┬──────┘
          ↓
   Candidate vN+1
          ↓
 Adversarial Review
          ↓
 Risks / Counterexamples
          ↓
 Prototype / Benchmark / Tests
          ↓
 Accept / Reject / Modify
          ↓
 Baseline vN+1
```

不是每轮都调用所有模型。下一轮只把算力投向 UNKNOWN 的高价值问题、P0/P1 风险、最低高价值能力桶、或模型意见冲突且可实验区分的问题。

## 7. 证据等级

- **E0 Opinion**：纯推测；
- **E1 Code Evidence**：代码/schema/API；
- **E2 Test Evidence**：自动测试；
- **E3 Measured Evidence**：benchmark/fault injection/prototype/migration rehearsal；
- **E4 Real Usage Evidence**：真实用户/真实数据/长期运行。

架构级修改原则上不能只靠 E0。数据库、付费工作流、批量处理、Provider failure 等关键结论尽量达到 E2/E3。

## 8. 关键失败场景

按改动相关性验证：Provider 429/5xx/timeout、API/schema/CORS 变化、网络中断、cache 爆满、disk full、SQLite lock/corruption、DB/文件写入部分成功、migration 中断、旧版本回退、NAI 已扣费但结果未知、批量换角色部分失败、Transform crash、plugin/provider crash 或越权、100k+ assets 性能、Remote 收藏来源失效、provenance 缺失。

不要为了覆盖清单而一次性建设复杂基础设施；先用实验确定风险。

## 9. 最终 Integrator / Judge

若干轮后再启用一个最强模型作为 Integrator。输入当前 Baseline、A/B/C 报告、benchmark/test/prototype、决策日志和被拒方案。它必须形成 Final Architecture Candidate，并对重大决策说明采用/拒绝及证据，区分 MUST / SHOULD / LATER / REJECTED，给出迁移顺序、rollback boundary、Feature Preservation Matrix、Capability Scorecard 和 UNKNOWN。

最后再由**不同模型**做一次 Final Red-Team Review。若只能产生局部优化，则冻结架构。

## 10. Architecture Freeze Gate / 停止条件

满足以下条件后停止继续烧算力：

- 现有稳定功能保留目标接近 100%；
- 用户资产兼容/迁移可回滚；
- **批量换角色等 Protected Strength 不退化**；
- 无未解决 P0/P1 架构风险；
- Provider 单点失败不拖垮 Local Library；
- 关键迁移/失败假设有 E2/E3；
- 核心能力桶没有明显 `<8.5` 的高价值短板；
- 差异化关键桶约 `9+`，而非所有桶追求 10；
- 新 Provider / Processor 不需要持续修改核心业务；
- 连续两轮 Review 只产生局部优化，不再出现架构级修改；
- 继续优化的预计收益低于复杂度、迁移和维护成本。

达到 Freeze Gate 后进入 implementation，不无限设计。

## 11. 第一轮可直接复制给 Cursor 的任务

### Architecture Optimizer

> 阅读本任务书、DECISIONS.md、STATUS.md、GATE_REVIEW.md、CLOUD_CHECKPOINT_REPORT.md、现有测试和相关生产代码。把 Acquire → Curate → Transform → Library、Remote/Local、Provider、Materialization、Provenance 和功能保全视为 Architecture Baseline v0。不要从零重做总体架构。找真正值得修改的错误抽象、遗漏边界、耦合、未来瓶颈和可以简化的地方；明确哪些设计已足够好、不应修改。所有重大建议给证据等级、迁移风险、验证方法和 rollback。禁止修改生产代码，先输出研究报告。

### Barrel Benchmark Researcher

> 阅读本任务书和仓库事实源。不要重新设计总体架构。建立当前 Capability Matrix，优先寻找用户价值高但成熟度不足的桶。针对选中的桶寻找 Best-of-Breed 开源项目，尽量阅读代码/测试/schema，说明对方为什么强、哪些机制适合 Nai学长、哪些不适合。每个建议给最小改动、验证方法、许可证/维护成本和 regression risk。禁止修改生产代码，先输出研究报告。

### Adversarial Reviewer

> 在 Architecture Optimizer 和 Barrel Benchmark Researcher 形成候选后运行。不要提出另一套宏大架构，而是尝试证明候选改进会失败。重点攻击过度设计、功能退化、批量换角色受损、数据迁移、Provider failure、SQLite/cache、重复 workflow、插件权限、性能和不可验证假设。每个高风险问题提出可执行反例、测试或 benchmark；没有证据标 UNKNOWN；合理设计写 KEEP。禁止修改生产代码。

## 12. 最终目标

最终不是获得“最复杂的架构”，而是获得**最适合 Nai学长工作室这个真实项目**的架构：保住成熟功能，强化换角色等差异化能力，让在线发现、本地资产、筛选和处理形成闭环，新数据源/爬虫/Processor 可低成本扩展，网络故障不影响本地核心，来源和处理历史可追踪，性能/迁移/恢复/安全/Windows 体验可验证，同时避免不必要的分布式和微服务复杂度。

> **不是重新发明 Nai学长，而是把已经很强的 Nai学长，用木桶标杆、对抗审查和实验证据反复磨到收敛。**
