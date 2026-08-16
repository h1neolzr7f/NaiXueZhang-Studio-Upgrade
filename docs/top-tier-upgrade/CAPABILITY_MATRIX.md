# Capability matrix (Phase 0)

Base: `h1neolzr7f/NaiXueZhang-Studio-Upgrade` @ `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`  
Mode: `CLOUD_WEB`  
Scoring: 0 none, 5 path works but weaker than benchmark, 8 production-usable for this product, 10 leading with evidence.  
Barrel score = minimum of **core=Y** rows. Current barrel: **6.0** (`post.pipeline` / `assist.tool_loop`). TTS is **not** a core barrel row.

| capability_id | user_journey_step | core | benchmark_project | current_behavior | evidence | score | target | decision | reason | acceptance |
|---|---|---|---|---|---|---|---|---|---|---|
| start.one_click_launch | 安装启动 | Y | NAI-Utility-Tool / Langbai | 一键包或 INSTALL.bat 建 venv；START_GALLERY.bat 选 runtime/venv、端口守卫、健康检查 | INSTALL.bat, START_GALLERY.bat, tests/test_startup_safety.py | 8.0 | 9.0 | implement | 启动链成熟；云端无法真机验证 | 解压双击健康通过并打开 `/` |
| start.loopback_trust | 安装启动 | Y | NyaNovel | 默认 127.0.0.1；非回环需显式开关；会话令牌 fail-closed | server.py, tests/test_p0_paid_security.py | 9.0 | 9.0 | exclude | 已是安全基线 | 远程无令牌不能写 |
| ingest.local_drop_nai_only | 导入图库 | Y | IIB / NAIWeaver | 仅 codex/qqgroup 拖入；parse_nai_image 拒 Comfy | routes/gallery.py, nai_image_metadata.py | 7.0 | 8.0 | implement | 准入正确；/app 图库页无拖入 | 非 NAI 被拒并回报 reason |
| search.fts_works_prompt | 索引搜索 | Y | IIB | 脏集增量 FTS + additive HTTP status/incremental；COUNT 仍可空 | search.py, gallery_index.py, routes/gallery.py | 7.5 | 8.0 | implement | HTTP 已加；无 10k 真机 | 翻页不丢不重 |
| restore.png_stealth_v4 | PNG 参数恢复 | Y | NAIWeaver | 嵌入 Comment 保留未知字段；无 text chunk 时回退 stealth 解析 | nai_image_metadata.py, nai_char_modules/snapshots.py | 8.0 | 9.0 | implement | 未知字段可编译报告；Studio 画布仍不读 mask | 拖入后可见 prompt/uc/seed/v4 槽 |
| gen.studio_frozen_txt2img | 生成 | Y | NyaNovel / NAIWeaver | /api/nai/generate 冻结 comment；默认 force_free | routes/nai.py, nai/generate.py | 7.0 | 8.0 | implement | 付费闸门是长板 | 未确认付费不发付费请求 |
| gen.img2img_inpaint_canvas | 生成 | Y | NAIWeaver | compile + Studio/classic 画布；从本库加载原图并画 mask | nai_char_modules/generation.py, StudioPage.tsx, web/studio.js | 7.5 | 8.0 | implement | 云端 UI 已接；未付费真机出图 | 能从本库图打开 img2img 并回填 |
| gen.cancel_balance_error | 取消/余额/错误 | Y | SANP / Langbai | 5xx/超时 billing_uncertain；账本不猜 Anlas；Studio 无取消按钮 | generation_jobs.py, nai/generate.py, usage_ledger.py | 8.0 | 9.0 | implement | 扣费语义强；缺预估与 UI 取消 | unknown 不能当没扣费重试 |
| post.pipeline | 后处理 | Y | SANP / NAI-Utility-Tool | Lanczos 超分默认可用并声明引擎；无 ANR 时 mosaic:unavailable，不中断流水线 | post_pipeline.py, tests/test_post_pipeline.py | 6.0 | 7.0 | replace | 打码仍依赖可选 ANR | 无 ANR 时超分仍可用且声明引擎 |
| publish.pixiv_browser | 发布 | Y | SANP | Playwright 本机 Chrome；Butler 只准备草稿 | pixiv_web_upload.py, butler/planning.py | 7.0 | 8.0 | implement | 比 Cookie 直传更安全 | 预检失败不上传 |
| recover.generation_unknown | 崩溃恢复 | Y | Langbai | running→unknown + recovered_after_restart | generation_jobs.py, tests/test_generation_jobs.py | 8.0 | 9.0 | implement | 已对齐崩溃≠没扣费 | 杀进程后 can_retry=false |
| assist.split_desks | 小祥/凑企鹅 | Y | LingChat | 分台白名单+执行期二次鉴权；一次性计划器 | butler/agents.py, tests/test_butler_agents.py | 7.0 | 8.0 | exclude | 分台是强项，不要合成单角色 | 小祥不能 generate_image |
| assist.tool_loop | Agent Tool Runtime | Y | LingChat | 内核经 chat/auto_exec 安全接入；planning.py 零 import | butler/tool_loop_bridge.py, butler/chat.py | 7.0 | 9.0 | implement | 只跑 read preview；付费仍 WorkflowRequest | 付费工具只产 WorkflowRequest |
| assist.memory_confirmed | 主动角色体验 | Y | LingChat | 已确认偏好、人格交接、静默/频率上限；须用户确认 | butler/companion_state.py, routes/butler.py | 6.5 | 8.0 | implement | v1.9 落地；无窥屏无钩子 | 跨会话只复述已确认偏好 |
| assist.tts | 语音 | N | LingChat | 未做；明确不进木桶 | companion_state.public_state tts.core=false | 0.0 | 5.0 | defer | TTS 不是强制核心能力 | 不做也不扣核心分 |
| assist.proactive_events | 主动角色体验 | Y | LingChat | 本地信号（Token/队列/脏索引/待确认记忆）；防打扰 | /api/companion/events, companion-dock.js | 6.0 | 7.0 | implement | 不自动强弹；静默时段可关 | 不打扰时不说话 |
| search.visual_similar | 图库复用 | N | IIB | 本地 dHash/pHash + similar/dup HTTP；无 embedding | gallery_index.py, routes/gallery.py | 6.5 | 7.0 | implement | HTTP 已加；非 10k 声明 | 默认本地，无密钥不出网 |
| lineage.recipe_object | 生成→发布 | N | Langbai | 无统一配方对象 | ROADMAP.md | 2.0 | 7.0 | implement | 血缘未闭合 | 成图能追溯素材→任务→发布 |

## Barrel

| 核心能力（验收总表） | 当前分 | 决定最低项的行 |
|---|---:|---|
| NAI 原生创作 | 7.5 | gen.img2img_inpaint_canvas（画布已接，未付费真机） |
| 批量生产 | 8.0 | gen.studio_frozen_txt2img / char-swap 预检 |
| 图库与资产复用 | 7.5 | search.fts_works_prompt |
| 后处理 | 6.0 | post.pipeline |
| 发布与恢复 | 7.0 | publish.pixiv_browser |
| 数据和付费安全 | 8.5 | recover.generation_unknown + P0 测试 |
| Agent Tool Runtime | 7.0 | assist.tool_loop（chat 只跑 preview） |
| 主动角色体验 | 6.0 | assist.proactive_events（TTS 不进木桶） |
| Windows 安装与上手 | 8.0 | 云端未真机验证，见 PENDING_LOCAL_WINDOWS |
| 文档与可验证性 | 7.5 | 本目录建立后提高 |

**barrel_lowest_capability:** `post.pipeline` / `assist.proactive_events`  
**barrel_lowest_score:** `6.0`  
TTS is not a core barrel item. v1.9 is implemented, not cancelled. Pixiv account work remains deferred. Windows WIN-001..015 remain local.
