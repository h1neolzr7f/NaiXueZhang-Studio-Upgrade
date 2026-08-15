# Nai学长工作室：多模型架构研究与升级方法论任务书

> Status: **Research Brief / 研究任务书**  
> Purpose: 供 Cursor 中多个顶级模型独立、交叉、反驳、迭代分析。  
> Repository: `h1neolzr7f/NaiXueZhang-Studio-Upgrade`  
> Working branch for current cloud checkpoint: `cursor/cloud-top-tier-integration-f036`  
> Important: **这不是既定最优架构，不是要求模型执行某个预选方案。本文描述的是现状、候选方向、约束、目标与研究方法。模型应主动提出更优替代方案，并用代码、测试、对标项目、失败场景和迁移成本论证。**

---

## 0. 给所有参与模型的总指令

你不是来“顺着现有方案夸它”的，也不是来快速生成一份重构清单。你要把这个仓库当成一个已经存在大量成熟功能、正处于高速迭代阶段、准备进入下一次架构收敛的软件产品，进行真正的软件架构研究。

请充分使用可用算力和上下文。不要因为第一次看到一个看似合理的架构就停止。至少完成：

1. **独立理解现有仓库和历史决策**；
2. **识别能力、边界、耦合、重复、技术债和现有优势**；
3. **对当前候选架构提出支持与反对证据**；
4. **搜索/研究同类或相邻领域的优秀开源项目，按能力而不是按整项目进行 Best-of-Breed 对标**；
5. **提出至少 2–4 套有实质差异的架构候选**，而不是同一方案换名字；
6. **对每套方案做迁移成本、功能保留、性能、可靠性、扩展性、可测试性、第三方数据边界、插件安全、用户体验评估**；
7. **设计可验证的实验、测试、基准和失败注入**；
8. **反驳自己最喜欢的方案**；
9. **在证据不足时明确写 UNKNOWN / NEEDS MEASUREMENT，不允许用“应该没问题”代替验证**；
10. 最后输出“当前最值得继续验证的候选及其证据”，但**不要因为本文给出了某个候选方向，就默认它是最终答案**。

### 禁止行为

- 不要为了“架构更漂亮”而删除已经能工作的成熟功能。
- 不要先决定重写，再倒推理由。
- 不要把所有功能塞进一个 God Service / God Agent / God Database。
- 不要为了引入某个流行框架而破坏已验证的稳定路径。
- 不要仅看 README；对关键结论必须读代码、测试、数据库/schema、API 契约和现有决策记录。
- 不要把“代码量变少”直接等同于“架构更好”。
- 不要把“拆成微服务”直接等同于“更专业”。当前产品本质上仍是 Windows/local-first 创作工作台，复杂部署本身是成本。
- 不要用 mock 通过代替真实边界验证；无法实测时写清楚。
- 不要为了通过质量门禁删除测试或降低门槛。

---

# 1. 项目背景与产品目标

Nai学长工作室最初从 NovelAI / Pixiv 图库与素材管理需求成长而来，随后逐步加入：

- 本地 NovelAI 图库与元数据验证；
- Prompt、角色、画风、Vibe、来源等资产管理；
- Pixiv / QQ / 本地导入等素材获取能力；
- AITag 在线发现；
- Studio；
- **批量换角色**；
- NovelAI 文生图 / 图生图 / inpaint 相关能力；
- 多 Token / 生成任务队列；
- 超分、打码、元数据清理等后处理；
- Pixiv 发布准备与相关流程；
- SQLite / FTS / 相似图 / 重复图能力；
- AI Butler、tool kernel、确认/审批、durable workflow；
- 本地记忆、主动事件、侧栏助手；
- Windows 一键包、安全与凭据保护；
- 其他已经存在于仓库但此清单未穷尽的功能。

项目下一阶段的目标不是“再堆几十个按钮”，而是判断是否应从“功能很多的 Gallery/Studio”进一步收敛成一个更清晰、更长期可扩展的 **Anime / NovelAI 创作资产与生产平台**。

### 产品层面希望最终达到的体验

用户不应该被迫先把互联网或第三方数据库整库下载到本机才能使用工具。

理想体验应支持：

- 在线发现和检索大量远程资产/知识；
- 只对用户真正收藏、下载、处理、生成的内容进行本地持久化；
- 用户能够快速筛选真正有价值的参考；
- 选中资产后可以直接进入换角色、Prompt 处理、NovelAI 生成、后处理等流水线；
- 处理结果自动沉淀回自己的本地资产库；
- 用户的数据、收藏、生成结果、处理历史和来源关系长期可追踪、可恢复；
- 数据源、搜索器、爬虫、Processor、生成后端可以逐步扩展，而不需要每接一个来源就重写核心图库；
- 现有成熟功能继续工作，用户旧图库和旧工作流不应因架构升级而被牺牲。

当前候选产品抽象可以简写为：

`获取数据 → 筛选数据 → 处理数据 → 沉淀/管理用户资产`

英文工作名：

`Acquire → Curate → Transform → Library`

**注意：这只是当前候选抽象。参与模型必须验证它是否真的适合本项目，必要时应提出更好的领域划分。**

---

# 2. 当前候选架构假设（必须验证，不得当成答案）

## 2.1 Online 与 Local 分离

候选思想：

- `Online` 是远程发现世界；
- `My Library` 是用户明确拥有/保存/生成/处理后的本地资产；
- 浏览远程内容不自动等价于下载永久资产；
- 只有用户明确操作或处理工作流需要时，才 materialize 指定内容。

需要模型验证：

- 是否会让 UI 变复杂？
- 收藏应该保存引用、快照还是完整资产？
- 在线源失效后收藏是否仍有价值？
- 哪些 metadata 需要轻量缓存？
- 是否需要 `Remote / Cached / Materialized` 三态甚至更多状态？
- 如何保证本地-first 与在线能力并存，而不变成必须联网？

## 2.2 Provider / Acquisition Adapter

候选思想：

远程 API、在线图库、在线数据库、网页 Provider、爬虫、浏览器插件、本地导入都属于“数据获取”的不同方式。

**爬虫不是产品架构的中心，而是 Acquire 的一种 Adapter。**

需要模型验证：

- Provider 与 Crawler 是否应该是同一个抽象？
- Provider 应暴露 capability negotiation 还是固定接口？
- 搜索、详情、预览、下载、metadata、分页、健康检查、鉴权应如何拆分？
- Provider 是否应运行在插件沙箱/子进程？
- Provider 失败、限流、CORS、API 变更时如何降级？
- 是否需要 circuit breaker、rate budget、backoff、缓存？

## 2.3 RemoteAsset 与 LocalAsset

候选思想：

远程结果不直接写 Library DB；先以统一远程资产引用存在，用户明确选择后再 materialize。

需要模型验证：

- 是否需要单一 `Asset` + lifecycle state，还是 `RemoteAssetRef` / `LocalAsset` 分类型更好？
- 统一资产模型应包含哪些稳定字段，哪些应保留 provider-native metadata？
- 是否应使用 source snapshot / version / etag？
- 图片、Prompt、角色、法典词条、实验记录是否都应该叫 Asset，还是需要多种 domain entity？
- 避免“Universal Asset Model 过度泛化”的具体边界是什么？

## 2.4 Curate

候选思想：

搜索、过滤、Tag、收藏、去重、相似图、质量排序、角色/画师/Prompt 发现等形成独立筛选层。

需要模型验证：

- 多 Provider 搜索结果如何统一 ranking？
- provider relevance 与 global ranking 如何融合？
- local + remote 联合检索的索引结构是什么？
- canonical tag / alias / multilingual concept 是否需要 Knowledge Layer？
- ranking 是否应单独作为引擎？
- 用户偏好学习是否值得做，如何避免把架构绑死在模型上？

## 2.5 Transform

候选思想：

现有成熟的处理功能都进入可组合 Transform / Workflow 层，包括但不限于：

- **批量换角色（必须保护的核心能力）**；
- Prompt 重组/清洗；
- NovelAI 生成；
- img2img / inpaint；
- 超分；
- 打码；
- 抠图；
- metadata 处理；
- 其他批处理能力。

需要模型验证：

- Processor 应是简单函数、节点、任务类型还是 workflow step？
- 哪些 Transform 适合 DAG，哪些不适合？
- 是否需要可复现 Recipe？
- 是否应该建立 non-destructive lineage？
- 原图、换角色派生图、超分图、最终发布图如何组织？
- 如何与现有 Butler/LangGraph durable workflow 配合，而不是重做一套任务系统？

## 2.6 Library

候选思想：

Library 是用户长期拥有的本地资产与关系，不是互联网镜像。

需要模型验证：

- 当前 SQLite per-gallery 模式是否继续合适？
- 是否需要 catalog DB + media storage 分离？
- 10k / 100k / 1M assets 的性能边界在哪里？
- FTS、感知哈希、语义 embedding 如何逐步演进？
- 文件系统才是 source of truth，还是 DB 才是 source of truth，还是混合？
- 备份、恢复、迁移、移动库、跨盘符、缩略图缓存如何设计？

---

# 3. 不可轻易破坏的现有优势（Protected Strengths）

这次研究不是绿地项目。参与模型必须先识别并保护已有价值。

至少包括：

## 3.1 批量换角色

这是当前产品中非常重要的差异化能力，不能因为新架构重构而丢失或退化。

研究目标不是“如何替换它”，而是：

- 如何让在线筛选结果可以直接进入批量换角色；
- 如何让换角色使用统一资产/工作流边界；
- 如何保留参数冻结、确认、失败恢复、结果归档；
- 如何把换角色前后形成可追踪 lineage / recipe；
- 如何在不破坏现有 UX 的情况下提高批量能力。

## 3.2 已有生成与后处理流水线

不要为了新 Pipeline 把已经能工作的生成、超分、打码、metadata 等功能重写成全新框架，除非有明确证据证明收益显著且迁移风险可控。

## 3.3 Butler / LangGraph durable workflows

仓库已有“交互式 Agent”和“耐久、有副作用、可能付费的工作流”分层思想。成本/副作用操作应继续保持审批、确认、持久化和恢复边界。

任何新架构都必须解释如何复用，而不是默认替换现有 durable runtime。

## 3.4 本地优先、安全与用户数据

已有：

- localhost 边界；
- Windows DPAPI；
- 付费操作确认；
- 路径边界；
- 数据不默认上传；
- 敏感扫描；
- 可恢复/审计思想。

这些属于产品质量，不应作为架构升级的牺牲品。

## 3.5 现有图库、搜索、索引、拖入、生成库、Studio、助手、发布等

**默认规则：功能保全。**

新架构上线时，旧稳定版可用功能的目标保留率应接近 100%。如果模型建议删除/合并/降级某功能，必须逐项说明：

- 为什么它是重复或错误能力；
- 用户替代路径是什么；
- 迁移后如何验证没有能力损失；
- 是否影响旧数据和旧用户。

---

# 4. “木桶标杆法”——本项目候选升级方法论

当前形成了一套需要进一步验证和完善的软件优化方法，暂称：

**Barrel Benchmark Method / 木桶标杆法**

其思想并非宣称原创理论，而是组合：

- capability-based assessment；
- benchmarking；
- gap analysis；
- best-of-breed；
- constraint-driven improvement；
- regression-gated iterative engineering。

## 4.1 基本流程候选

1. 把整个项目拆成可独立评价的 Capability；
2. 每个 Capability 记录当前真实实现和证据；
3. 给出成熟度/质量评分，但评分必须绑定证据，不允许凭感觉；
4. 找最低桶和最重要瓶颈；
5. 每个桶分别寻找该领域优秀开源项目/产品，而不是找一个“大而全竞品”全盘照搬；
6. 研究对标项目的**代码、架构、数据结构、失败处理、测试、用户体验**；
7. 只吸收能解决当前 Gap 的机制，不复制无关复杂度；
8. 保护本项目已更强的能力，不允许“向标杆倒退”；
9. 实现最小可验证升级；
10. 加回归、故障注入、性能测试；
11. 重新评分；
12. 再选择下一块短板；
13. 当所有核心桶达到目标且边际收益显著降低时停止，避免无限架构化。

## 4.2 参与模型必须研究这套方法本身

请不要只使用它。也要分析它是否存在以下缺陷：

- 局部最优拼接导致整体不一致；
- 各 Best-of-Breed 项目采用不同哲学，组合后耦合反而更高；
- 过度追求最低桶导致忽略真正的差异化优势；
- 评分主观；
- benchmark selection bias；
- 为追求 9/10、10/10 产生不必要复杂度；
- 过度对标成熟大型项目，给本地单机工具引入不相称基础设施；
- 技术指标提高但 UX 变差；
- 功能保留导致架构永远无法清理旧债；
- 高速迭代期过早冻结抽象。

请提出改进后的方法论，例如是否需要：

- 核心/非核心桶；
- Protected Strength；
- Architecture Fitness Functions；
- Stop Conditions；
- Weighted Bottleneck；
- Cost of Complexity；
- User Journey Score；
- Migration Risk Score；
- Dependency Risk；
- Evidence Confidence；
- Feature Preservation Gate。

不要默认上述术语都必须采用，请自己论证。

---

# 5. 需要建立的能力矩阵（模型应补全，不得只照抄）

下面只是起始集合。请读仓库后补充/拆分/合并。

| Capability Bucket | 需要研究的核心问题 |
|---|---|
| Acquire | API / crawler / import / browser extension / remote sources 如何统一或分层 |
| Provider Runtime | capability、健康检查、限流、缓存、故障隔离、插件边界 |
| Online Discovery | 多源浏览、分页、预览、联合搜索、offline fallback |
| Curate/Search | FTS、tag、facet、排序、过滤、收藏、selection set |
| Similarity/Dedupe | SHA、dHash/pHash、embedding、派生关系 |
| Knowledge/Codex | tag、prompt、法典、artist、alias、来源与授权边界 |
| Ranking | 多 Provider 归一化、global score、个人偏好 |
| Local Library | SQLite、文件生命周期、album、collection、备份、移动 |
| Asset Model | identity、source、metadata、remote/local lifecycle |
| Provenance/Lineage | source → recipe → task → output → postprocess → publish |
| Transform | 批量换角色、Prompt、图生图、inpaint、后处理 |
| Workflow | durable jobs、恢复、幂等、审批、付费边界 |
| NAI Integration | 参数编译、token、生成、模型版本、失败语义 |
| Cache | preview、metadata、thumbnail、LRU、materialized protection |
| Plugin/Extension | Provider/Processor 扩展、安全、版本兼容 |
| Migration | schema version、backup、rollback、library compatibility |
| Observability | logs、metrics、health、task trace、diagnostics |
| Security | secret、path、localhost、plugin capability、source policy |
| UI/UX | Online/My Library、状态表达、批量操作、低学习成本 |
| Performance | 10k/100k/1M、thumbnail、FTS、queue、memory |
| Packaging | Windows one-click、升级、恢复、依赖体积 |
| Agent | interactive tool loop 与 durable workflow 的边界 |
| Testing | contract、integration、fault injection、migration、perf |

要求每个桶输出：

- 当前实现；
- 当前证据；
- 当前分数及置信度；
- 用户价值权重；
- 架构风险权重；
- 候选标杆项目；
- 可借鉴机制；
- 不应借鉴的部分；
- 升级候选；
- 验证方法；
- 回滚策略；
- 升级后的预期分数；
- 是否会伤害其他桶。

---

# 6. 对标研究规则

## 6.1 不寻找“一个最像的项目”

不同能力应独立寻找 best-of-breed 或 highly relevant reference。

示例方向（仅为搜索启发，不代表本文已经选定它们）：

- 数据获取/下载框架；
- 数字资产管理 / photo DAM；
- 自托管图片库；
- tag / booru 搜索系统；
- NovelAI tag/codex 工具；
- workflow / DAG / durable execution；
- plugin/extension host；
- schema migration；
- desktop local-first application；
- image similarity；
- metadata/provenance；
- prompt/versioning；
- UI/UX 优秀的本地工具。

模型应自行找项目，不必限制在已知名单。

## 6.2 每个标杆必须回答

1. 它解决什么问题？
2. 它为什么在这个能力上强？
3. 代码/数据结构/测试中的证据是什么？
4. 它的规模和约束是否与本项目可比？
5. 哪些机制可以移植？
6. 哪些机制移植会过度工程化？
7. 许可证/数据授权是否允许借鉴代码或只适合借鉴思想？
8. 如果采用，会影响现有哪条路径？
9. 需要增加哪些回归测试？
10. 如果不采用，理由是什么？

---

# 7. 第三方在线数据库与数据边界

本项目可能接入在线图库、标签/法典、元数据站点、booru、Pixiv 等来源。

研究时必须区分：

- 软件代码许可；
- 数据库结构/汇编权；
- 词条文本权利；
- 图片权利；
- API/网站 Terms；
- 用户自己获取数据与项目打包再分发数据的区别。

候选原则：

- 项目本身尽量不预装第三方内容数据库；
- 在线 Provider 不等于获得整库镜像权；
- 用户明确保存单项内容与项目服务器镜像整库是不同风险；
- 任何本地 materialized asset 尽量保留来源/作者/URL/license-or-rights 元数据（如可得）；
- 对授权不明确的数据源，应设计可关闭、可降级、可替换的 Provider 边界。

参与模型应进一步判断：这个原则是否足够，以及技术上如何避免“前端不落库但实质上重新分发整个第三方数据库”的灰区。

---

# 8. 迁移策略必须是架构设计的一部分

这是一个已有用户数据、已有 Release、已有工作流的软件，不允许把 migration 当成实现后再补。

每套架构候选都必须说明：

## 8.1 功能迁移

- 旧 Gallery 如何进入新结构；
- 旧 crawler 如何保留；
- 批量换角色如何保持原路径可用；
- Studio / generated gallery / post pipeline 如何迁移；
- 旧 API 如何兼容；
- Butler / workflow 如何接入；
- UI 是否支持渐进迁移。

## 8.2 数据迁移

至少研究：

- schema version；
- migration journal；
- pre-migration backup；
- integrity check；
- rollback；
- interrupted migration；
- 大图库迁移耗时；
- 老版本回退后的兼容性；
- 不同盘符/目录移动；
- Windows 文件锁和长路径。

## 8.3 Strangler / Adapter 是否适合

请判断是否应采用渐进式替换，而不是 Big Bang rewrite。不要默认答案，需结合当前代码结构论证。

---

# 9. 目标效果：最终用户应该感受到什么

架构不是为了架构图。最终升级应该可被普通用户感知。

候选目标效果：

## 9.1 找素材更快

用户可以在一个统一入口搜索多个来源和本地资产，不必打开多个站点、复制多个 Prompt、手动建文件夹。

## 9.2 本地库不再被无意义数据淹没

远程内容可以浏览、预览、筛选；只有真正需要的内容才成为长期本地资产。

## 9.3 从“看到喜欢的内容”到“开始创作”的路径更短

例如：

`在线发现 → 选中若干参考 → 批量换角色 → NAI → 后处理 → 自动入库`

用户不需要在多个软件之间反复导入导出。

## 9.4 所有已有能力变得更连贯

不是重新造换角色、重新造图库、重新造生成器，而是让它们使用更清楚的数据与工作流边界。

## 9.5 故障局部化

某个 Provider 挂掉，不影响本地图库、换角色、生成和其他 Provider。

## 9.6 数据可追踪

用户能回答：

- 这张图来自哪里？
- 原始 Prompt 是什么？
- 我什么时候保存的？
- 它经过哪次换角色？
- 用什么 NAI 参数生成？
- 做过哪些后处理？
- 最终版本和原始版本是什么关系？

## 9.7 扩展成本下降

未来新增来源时，应尽量只新增 Provider/Adapter，而不是修改 Gallery、Search、Transform、Library 多处。

未来新增处理功能时，应尽量成为 Processor/Workflow step，而不是重新复制一套批处理框架。

## 9.8 旧用户感觉是“升级”，不是“换了一个软件”

旧功能、旧数据、核心操作习惯尽可能保留；新架构的复杂度不应暴露给普通用户。

---

# 10. 架构质量目标与硬性验收候选

以下指标不是最终数值，请模型评估是否合理并提出更科学指标。

## 10.1 功能保全

- 目标：现有成熟用户功能保留率接近 **100%**。
- 任何删减必须有替代能力和明确理由。

## 10.2 数据兼容

- 旧图库在升级后不丢数据；
- migration 前可备份；
- migration 失败可恢复；
- provenance 不应覆盖/破坏原始 metadata。

## 10.3 Provider 隔离

- Provider 不直接写核心 Library DB；
- Provider failure 不拖垮其他来源和本地库；
- Provider 能力可探测；
- timeout/rate-limit/error 有统一语义。

## 10.4 Selected-only materialization

- 浏览 10,000 条 remote result 不等于永久下载 10,000 条；
- batch workflow 只 materialize 选中的资产或必要输入；
- Cache 和 Permanent Asset 必须有不同生命周期。

## 10.5 批量换角色不退化

至少保持：

- 当前主要入口可用；
- 批量预检/确认；
- 生成任务可恢复；
- 结果归档；
- 不因新 Asset Model 明显增加用户操作步骤。

## 10.6 性能

设计并实测：

- 10k；
- 100k；
- 在合理环境下尽可能探索 1M metadata rows / remote references 的瓶颈。

不要假设所有用户都有服务器级硬件。

## 10.7 Architecture Fitness Functions

请提出可自动化检查的架构约束，例如：

- Provider package 禁止 import 某些 Library persistence internals；
- durable paid action 不允许绕过 WorkflowRequest / confirm path；
- planning layer 不直接依赖 tooling；
- migration 必须有 downgrade/backup contract；
- remote browsing 不得静默 materialize full asset；
- plugin 无权限时不得读 Secret。

这些只是例子，请结合仓库提出真正适用的规则。

---

# 11. 必须考虑的失败场景

任何候选架构如果只在 happy path 上漂亮，不算通过。

至少分析：

- Provider API 改版；
- Provider 429；
- Provider 5xx；
- 网络中断；
- CORS 改变；
- 远程图片失效；
- remote metadata 与 local snapshot 不一致；
- 用户一次选中 1000+ assets；
- materialize 中途磁盘满；
- 文件已下载但 DB transaction 失败；
- DB 已写但文件 rename 失败；
- Windows Defender/文件占用；
- SQLite database locked；
- migration 中断；
- 生成任务进程崩溃；
- NAI 请求已扣费但客户端不知道结果；
- batch character replacement 部分成功、部分失败；
- thumbnail cache 损坏；
- duplicate detector 错判；
- plugin crash；
- plugin 恶意/越权；
- 用户回退旧版本；
- 远程来源授权/政策发生变化，需要禁用 Provider 但保留本地 provenance。

每个关键失败场景必须说明：

- detectable?；
- retryable?；
- idempotent?；
- recoverable?；
- user-visible state?；
- audit/provenance?。

---

# 12. 多模型协作与迭代流程

本文件专门用于同时交给多个顶级模型。为了避免 groupthink，请按以下方式工作。

## Round 1 — Independent Audit

每个模型独立完成，不读取其他模型结论（如果工作流允许）。

输出：

- 对现有系统的理解；
- 当前最强能力；
- 当前最危险技术债；
- 对 `Acquire → Curate → Transform → Library` 的支持/反对；
- 认为真正的 domain boundaries；
- 3–10 个需要深入对标的能力；
- 至少 2 套架构候选；
- 最关键 UNKNOWN。

## Round 2 — Benchmark Deep Dive

不同模型可以分别负责不同桶，但每个桶至少有两个模型交叉检查。

要求：

- 搜索优秀开源项目；
- 读代码与测试；
- 对比当前仓库；
- 输出“可借鉴机制 / 不应借鉴机制 / 迁移风险”。

## Round 3 — Adversarial Review

让模型 A 专门攻击模型 B 的方案。

重点：

- 隐藏耦合；
- 数据迁移；
- 性能；
- 用户操作变复杂；
- over-engineering；
- 授权/外部依赖；
- Windows/local-first 适配；
- feature regression；
- 维护者未来成本。

## Round 4 — Prototype / Measurement Plan

不要直接全量重构。先设计能区分不同候选优劣的最小实验。

例如：

- Provider contract spike；
- 远程 100k refs ranking benchmark；
- RemoteAsset→Local migration spike；
- character replacement adapter spike；
- cache eviction experiment；
- schema migration fault injection；
- plugin crash isolation；
- local+remote unified search prototype。

每个实验必须明确“什么结果支持 A，什么结果否定 A”。

## Round 5 — Synthesis

只有完成前面轮次后，才做综合。

输出：

- 保留的候选；
- 被证伪的候选；
- 仍未知的点；
- 推荐继续验证的方向；
- 不做什么；
- 第一阶段最小迁移范围；
- rollback path；
- 需要冻结的接口；
- 下一轮证据收集。

## Round 6+ — Iterative Refinement

如果仍存在重大不确定性，继续迭代，不要因为已经写了一份“最终设计文档”就停止。

每轮只允许在新增证据后提高置信度。

---

# 13. 每个模型的标准输出模板

建议严格按以下结构输出，便于后续模型比较。

## A. Executive Summary

- 当前架构健康度：x/10（置信度 x%）
- 当前最强 5 桶
- 当前最弱 5 桶
- 最大单点风险
- 是否支持当前候选四段式架构：支持 / 部分支持 / 反对

## B. Repository Evidence

逐条给出文件、模块、接口、测试、schema 证据。

## C. Capability Matrix

每桶：Current / Target / Benchmark / Gap / Risk / Evidence Confidence。

## D. Architecture Candidates

至少 2–4 套真正不同方案。

对每套：

- 核心抽象；
- 数据流；
- 组件边界；
- 与现有代码映射；
- 优点；
- 缺点；
- 迁移路径；
- 失败模式；
- 需要的验证；
- 复杂度成本。

## E. Best-of-Breed Research

按桶列对标项目与可借鉴点。

## F. Feature Preservation Audit

逐项检查现有功能不会丢。

重点必须包含：

- 批量换角色；
- Studio；
- generated gallery；
- crawler/import；
- search/index；
- NovelAI generation；
- postprocess；
- Butler/workflow；
- assistants；
- Windows packaging；
- security/credentials；
- publish path；
- 其他从仓库实际发现的功能。

## G. Migration Plan

包括数据、API、UI、任务、兼容层、回滚。

## H. Validation Plan

- unit；
- contract；
- integration；
- fault injection；
- migration；
- performance；
- UX journey；
- security。

## I. Self-Critique

至少写：

- 本方案最可能错在哪里；
- 哪个假设未经验证；
- 什么测试结果会让我改变结论；
- 是否存在更简单方案。

## J. Next Evidence

只列下一轮最值得获取的证据，不要直接开大规模重构。

---

# 14. 当前仓库需要优先阅读的材料

开始前至少阅读：

- `README.md`
- `ROADMAP.md`
- `CONTRIBUTING.md`
- `docs/UPGRADE.md`
- `docs/top-tier-upgrade/CLOUD_CHECKPOINT_REPORT.md`
- `docs/top-tier-upgrade/GATE_REVIEW.md`
- `docs/top-tier-upgrade/RUN_STATE.json`
- `docs/top-tier-upgrade/STATUS.md`
- `docs/top-tier-upgrade/DECISIONS.md`
- `docs/top-tier-upgrade/CAPABILITY_MATRIX.md`
- `docs/top-tier-upgrade/OWNERSHIP.md`
- `docs/top-tier-upgrade/NEXT_ACTION.md`
- 与 gallery、crawler、nai、butler、tooling、workflow、migration、tests 相关的真实代码。

**注意**：`CLOUD_CHECKPOINT_REPORT.md` 是 checkpoint，不是整个升级完成证明。当前 Draft PR 也不是“已经可以直接 merge”的最终证明。

---

# 15. 当前已知的研究问题清单

这些问题可以被推翻、合并、扩展。

1. `Acquire → Curate → Transform → Library` 是否真的是最适合本项目的四个 domain？
2. Provider 与 Crawler 的正确关系是什么？
3. Remote 与 Local 应该是两种实体还是一个 lifecycle？
4. “所有东西都是 Asset”是否会过度抽象？
5. 法典词条、Prompt、角色、图片是否需要不同领域模型？
6. 多来源联合搜索是否值得在第一阶段做？
7. global ranking 的真正用户价值有多大？
8. canonical tag/knowledge graph 是核心还是过度工程？
9. SQLite 能否继续作为长期主库？
10. 是否需要 object store 风格目录？
11. 当前 gallery index 应如何演进？
12. provenance 应作为 first-class table 还是 event log？
13. Transform 是否需要 DAG？
14. Recipe 与 lineage 应如何区别？
15. Butler/LangGraph 与新的 Processor orchestration 如何分工？
16. 批量换角色如何在新架构中成为 first-class workflow 而不改坏现有能力？
17. cache 与 materialized asset 的状态机是什么？
18. Provider plugin 是否值得第一阶段就开放给第三方？
19. plugin 隔离做到什么程度才符合本地桌面工具的成本收益？
20. migration 如何支持连续快速迭代？
21. 是否应该冻结一个长期 API/SDK，还是当前仍太早？
22. 哪些功能应该继续保持专用实现，不能为了统一而强行抽象？
23. 哪些历史功能实际上已经重复，是否可以通过 UX 合并但保留能力？
24. 当前多入口/经典 UI/`/app` 是否需要统一？何时统一风险最低？
25. 在线数据库只是 Remote Provider，还是需要独立 Knowledge Domain？
26. 第三方网站授权变化时技术架构如何快速关闭/替换来源？
27. 用户真正最常用的 3 条 journey 是什么？架构是否围绕它们优化？
28. 木桶标杆法应如何避免局部最优和过度工程？
29. 最低桶是否应该按用户价值加权，而非单纯取最低分？
30. 什么条件下应该宣布“架构冻结”，停止继续大改？

---

# 16. 成功标准

这轮多模型研究成功，不等于产出一张最复杂的架构图。

成功应该表现为：

1. 对现有仓库的能力和债务有可复核证据；
2. 至少多个真实可行架构候选经过互相攻击；
3. 每个关键能力都有合理 benchmark，而不是一个项目包打天下；
4. 现有优势特别是批量换角色等被明确保护；
5. 迁移成本和 rollback 被当成架构一部分；
6. 用户体验和本地-first 约束没有被“工程洁癖”牺牲；
7. 关键 UNKNOWN 被转成可执行实验；
8. 通过 prototype / benchmark / fault test 消灭假设；
9. 最终选择建立在证据上，而不是模型偏好或流行架构；
10. 得到一个能支撑未来多年迭代、但复杂度仍与项目规模匹配的架构和升级方法。

---

# 17. 最后提醒

**不要急着写最终方案。**

这个项目已经在很短时间内经历了多次架构演进，现在最需要的是“收敛”，不是为了追求完美继续无限重构。

因此你的任务同时包含两个方向：

- 找到现有架构真正需要升级的部分；
- 找到应该停止升级、保持原样的部分。

一个优秀结论应能够明确说：

> 哪些地方必须改，为什么；  
> 哪些地方可以改，但现在不值得；  
> 哪些地方看起来不够优雅，却应该因为稳定、兼容、用户价值而保留。

请用实际仓库和实验证据，让下一次架构升级成为**能力收编、边界收敛、品质提升**，而不是又一次大规模重做。
