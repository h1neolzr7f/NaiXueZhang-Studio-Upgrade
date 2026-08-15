# Capability matrix (Phase 0)

Base: `h1neolzr7f/NaiXueZhang-Studio-Upgrade` @ `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`  
Mode: `CLOUD_WEB`  
Scoring: 0 none, 5 path works but weaker than benchmark, 8 production-usable for this product, 10 leading with evidence.  
Barrel score = minimum of **core=Y** rows. Current barrel: **4.0** (`assist.memory_tts_emotion`, deferred v1.9). Next implementable lowest: **6.0** (`gen.img2img_inpaint_canvas` compile without canvas UI).

| capability_id | user_journey_step | core | benchmark_project | current_behavior | evidence | score | target | decision | reason | acceptance |
|---|---|---|---|---|---|---|---|---|---|---|
| start.one_click_launch | 安装启动 | Y | NAI-Utility-Tool / Langbai | 一键包或 INSTALL.bat 建 venv；START_GALLERY.bat 选 runtime/venv、端口守卫、健康检查 | INSTALL.bat, START_GALLERY.bat, tests/test_startup_safety.py | 8.0 | 9.0 | implement | 启动链成熟；云端无法真机验证 | 解压双击健康通过并打开 `/` |
| start.loopback_trust | 安装启动 | Y | NyaNovel | 默认 127.0.0.1；非回环需显式开关；会话令牌 fail-closed | server.py, tests/test_p0_paid_security.py | 9.0 | 9.0 | exclude | 已是安全基线 | 远程无令牌不能写 |
| ingest.local_drop_nai_only | 导入图库 | Y | IIB / NAIWeaver | 仅 codex/qqgroup 拖入；parse_nai_image 拒 Comfy | routes/gallery.py, nai_image_metadata.py | 7.0 | 8.0 | implement | 准入正确；/app 图库页无拖入 | 非 NAI 被拒并回报 reason |
| search.fts_works_prompt | 索引搜索 | Y | IIB | 脏集增量 FTS + 全量 repair；COUNT 仍可空 | search.py, gallery_index.py, db.py | 7.0 | 8.0 | implement | 增量库已落地；无 10k 真机、无 HTTP 路由 | 翻页不丢不重 |
| restore.png_stealth_v4 | PNG 参数恢复 | Y | NAIWeaver | 嵌入 Comment 保留未知字段；无 text chunk 时回退 stealth 解析 | nai_image_metadata.py, nai_char_modules/snapshots.py | 8.0 | 9.0 | implement | 未知字段可编译报告；Studio 画布仍不读 mask | 拖入后可见 prompt/uc/seed/v4 槽 |
| gen.studio_frozen_txt2img | 生成 | Y | NyaNovel / NAIWeaver | /api/nai/generate 冻结 comment；默认 force_free | routes/nai.py, nai/generate.py | 7.0 | 8.0 | implement | 付费闸门是长板 | 未确认付费不发付费请求 |
| gen.img2img_inpaint_canvas | 生成 | Y | NAIWeaver | compile 已出 img2img/infill；Studio 无蒙版画布 | nai_char_modules/generation.py, tests/test_nai_generate_compile.py | 6.0 | 8.0 | implement | 编译层已锁；UI 画布未做 | 能从本库图打开 img2img 并回填 |
| gen.cancel_balance_error | 取消/余额/错误 | Y | SANP / Langbai | 5xx/超时 billing_uncertain；账本不猜 Anlas；Studio 无取消按钮 | generation_jobs.py, nai/generate.py, usage_ledger.py | 8.0 | 9.0 | implement | 扣费语义强；缺预估与 UI 取消 | unknown 不能当没扣费重试 |
| post.pipeline | 后处理 | Y | SANP / NAI-Utility-Tool | Lanczos 超分默认可用并声明引擎；无 ANR 时 mosaic:unavailable，不中断流水线 | post_pipeline.py, tests/test_post_pipeline.py | 6.0 | 7.0 | replace | 打码仍依赖可选 ANR | 无 ANR 时超分仍可用且声明引擎 |
| publish.pixiv_browser | 发布 | Y | SANP | Playwright 本机 Chrome；Butler 只准备草稿 | pixiv_web_upload.py, butler/planning.py | 7.0 | 8.0 | implement | 比 Cookie 直传更安全 | 预检失败不上传 |
| recover.generation_unknown | 崩溃恢复 | Y | Langbai | running→unknown + recovered_after_restart | generation_jobs.py, tests/test_generation_jobs.py | 8.0 | 9.0 | implement | 已对齐崩溃≠没扣费 | 杀进程后 can_retry=false |
| assist.split_desks | 小祥/凑企鹅 | Y | LingChat | 分台白名单+执行期二次鉴权；一次性计划器 | butler/agents.py, tests/test_butler_agents.py | 7.0 | 8.0 | exclude | 分台是强项，不要合成单角色 | 小祥不能 generate_image |
| assist.tool_loop | Agent Tool Runtime | Y | LingChat | 内核含 compile preview / 幂等 / 未接入 planning.py | butler/tooling/, tests/tooling/ | 6.0 | 9.0 | implement | 内核已扩，未接入聊天 | 付费工具只产 WorkflowRequest |
| assist.memory_tts_emotion | 主动角色体验 | Y | LingChat | 无长期记忆/TTS/窥屏 | butler/planning.py, companion-dock.js | 4.0 | 6.0 | defer | v1.9；不做窥屏 | 跨会话只复述已确认偏好 |
| search.visual_similar | 图库复用 | N | IIB | 本地 dHash/pHash + similar/dup 库函数；无 HTTP、无 embedding | gallery_index.py, tests/test_gallery_index.py | 5.0 | 7.0 | implement | 云端库级可用；非 10k 声明 | 默认本地，无密钥不出网 |
| lineage.recipe_object | 生成→发布 | N | Langbai | 无统一配方对象 | ROADMAP.md | 2.0 | 7.0 | implement | 血缘未闭合 | 成图能追溯素材→任务→发布 |

## Barrel

| 核心能力（验收总表） | 当前分 | 决定最低项的行 |
|---|---:|---|
| NAI 原生创作 | 6.0 | gen.img2img_inpaint_canvas（无画布 UI） |
| 批量生产 | 8.0 | gen.studio_frozen_txt2img / char-swap 预检 |
| 图库与资产复用 | 7.0 | search.fts_works_prompt |
| 后处理 | 6.0 | post.pipeline |
| 发布与恢复 | 7.0 | publish.pixiv_browser |
| 数据和付费安全 | 8.5 | recover.generation_unknown + P0 测试 |
| Agent Tool Runtime | 6.0 | assist.tool_loop（未接入聊天） |
| 主动角色体验 | 4.0 | assist.memory_tts_emotion（v1.9 defer） |
| Windows 安装与上手 | 8.0 | 云端未真机验证，见 PENDING_LOCAL_WINDOWS |
| 文档与可验证性 | 7.5 | 本目录建立后提高 |

**barrel_lowest_capability:** `assist.memory_tts_emotion`  
**barrel_lowest_score:** `4.0`  
v1.9 is deferred. Next implementable lowest is `gen.img2img_inpaint_canvas` at 6.0 (compile landed, no Studio canvas). Pixiv account work remains deferred.
