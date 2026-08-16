# Windows Final QA 验收报告

Date: 2026-08-16  
Role: Windows Final QA + Fix + Release Engineer  
Branch: `cursor/autonomous-next-architecture-96fe`  
Draft PR: https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/12  
Worktree: `E:\Packages\releases\NaiXueZhang-Studio-Upgrade-96fe`  
**Verdict: LOCAL WINDOWS RC: PASS**

Do not treat this as a public GitHub Release. Paid NovelAI and Pixiv login were not executed.

## 实际完成了什么

- 接手 `96fe` @ `6a7ef99`，以仓库文档和 PR #12 为事实源，没有重开架构。
- 修了 Windows CI 红：`Asia/Tokyo` quiet hours 在 `windows-latest` 缺 IANA 库时静默回落到 UTC。
- 修了本机才能打到的启动/门禁/UX 洞，并补回归。
- 用隔离 `data_dir`（不写真实 Token/图库）跑通一键启动、旧库索引、Online→Favorite→Materialize→Derive、Studio/换角授权边界。
- 全量 pytest 连续两轮绿；quality gate 两轮 `p0=p1=p2=0`；敏感扫描 clean。

## 发现并修复了什么

| 级别 | 问题 | 修复 |
|---|---|---|
| P1 | PR #12 Windows CI：`test_quiet_hours_use_configured_non_utc_timezone` 失败。core lock 无 `tzdata`，`ZoneInfo("Asia/Tokyo")` 回落 UTC | `tzdata==2026.2` 进入 `requirements.core.lock.txt`；companion 显式依赖；补 IANA 测试 |
| P1 | `START_GALLERY.bat` 隐藏拉起把日志追加到共用 `logs/server.log`。文件被占时 `cmd >> log` 挂起，健康检查永远等不到端口 | 改为 `logs/server-%GALLERY_PORT%.log`；健康等待 15→60 次 |
| P1 | Doctor 在 GBK PowerShell 5 下把 `一键启动.bat` 判缺失 | 用 Unicode 码位探测；便携 runtime 无 pip 时改查 `.venv` |
| P2 | no-direct-write 守卫扫进本机 `runtime/Lib/site-packages/torch` | 跳过 `runtime` / `.venv` / `.tmp` / `site-packages` |
| P2 | 经典「在线发现」沿用本地默认检索词 `NAI`，合成源 0 条，面板像坏了 | 无结果时回退空查询并标明本地库不受影响 |
| P2 | Online E2E 收藏 lifecycle 读到 `config.json` 里已入库的 `syn-1` | 测试隔离 `_is_materialized` |

## 全量测试结果

| 检查 | Pass 1 | Pass 2 |
|---|---|---|
| `pytest -q --ignore=tests/test_pixiv_selector_probe.py` | 1 fail（E2E 隔离泄漏，已修）→ 修后单测绿 | **1269 passed, 14 skipped, 127 subtests** |
| `product_quality_gate.py --json` | p0=p1=p2=0 | p0=p1=p2=0 |
| `scan_sensitive.py --git-candidates --content-only` | clean | — |
| `compileall` / `asset_versions.py --check` | 通过 | 通过 |
| Windows：`test_startup_safety` + `test_plaintext_at_rest` | 27 passed | 24 passed（改 log 名后） |
| Doctor | 中文启动器 FAIL → 已修为 OK | OK |
| 本轮变异：去掉在线回退文案 | RED | 恢复 GREEN |

Windows 比 Linux 多跑启动器/DPAPI，所以是 1269/14 而不是云端的 1211/68。

## Windows 真机结果

| 项 | 结果 |
|---|---|
| 真实用户数据 | **未写入**。RC 服务用 `.tmp/windows-rc-data`（旧库副本，无 Token） |
| 8797 | 仍被 `E:\验收临时\奶学长工作室` v1.5.0 占用，未杀 |
| 一键启动冷启动 | `GALLERY_PORT=8803` + 便携 runtime：**Server is up**（16s） |
| 已在运行 | 8798 检测为本项目进程，未误杀 |
| 便携 runtime 直启 | 8798 健康；`online-discover.js?v=` 200 |
| 旧图库副本 | 36 works / 339 images；incremental `unindexed=0` |
| 501 中文+撇号路径续扫 | 测试通过 |
| Online search `NAI` | 0 条（合成源不匹配，属实） |
| Online search 空查询 | 2 条合成卡 |
| Favorite | 不落图片文件 |
| Materialize | 入 `codex`，旧搜索 JSON 仍有 `WorkRef` |
| free-safe derive | `paid=false`，子作品带 parent |
| Studio 未确认 txt2img | `ticket=""`，免费标准路径 |
| Studio 未确认 img2img | `requires_ticket=true`，`ticket=""` |
| 换角未确认 | `ticket=""`；`confirmed=true` 才发票 |
| 真实 Token | 用户授权后写入隔离目录 DPAPI（`dpapi:v1:`，无明文）。未写入 `E:\aitag-mirror` 或一键包 `data/` |
| Live2D 资源 | `companions.json` / `tomori/casual` / `sakiko/causal` 的 `model.json` 在 8798 上均为 HTTP 200 |

## 2026-08-16 晚间补测（不拷贝 13GB 旧库）

对 `E:\aitag-mirror\data\aitag.db` **只读**打开，没有复制 5.4GB 库或 3.4 万张图。

| 项 | 结果 |
|---|---|
| 库规模 | 5.287 GB db；34658 works；370591 work_images；33230 已下载且有 local_path |
| 类型 | NAI 33863 / NAI_X 770 / SD 14 / ComfyUI 11 |
| 抽查文件 | 40/40 `local_path` 在 `E:\aitag-mirror\data\images` 存在 |
| 首页 60 条 | 6.3 ms |
| FTS `1girl` | 3.5 ms，命中 60 |
| COUNT 有路径图 | 1132.7 ms（5.4GB 库上最慢的一条只读查询） |
| Token | 隔离 `.tmp/windows-rc-data/nai_token.local.json`，DPAPI，`pst-` 不在文件里 |
| `/api/nai/tokens` | 8798 看到 1 个 novelai 槽，masked |
| `/api/nai/authorize` | 免费标准路径：`free_eligible=true`，`ticket=""`，`nai-diffusion-4-5-full` 832×1216 / 23 steps |
| HTTP `/api/nai/generate` | 入队成功，但卡在 `queue_position=3`。隔离 `generation_jobs.json` 里有 pytest 留下的 `terminal=false` 假任务堵队列 |
| 直连 `generate_image` | `connect_failed`：本机到 `image.novelai.net` / `api.novelai.net` TLS 超时。`request_attempted=false`，**未扣 Anlas** |
| 本机放大 | 抽 1 张已有 PNG 做 Lanczos 2x → `.tmp/upscale-probe/probe_up2x.png`（3.3 MB，708 ms）。GPU 206→290 MiB，这是 CPU 缩放，不是 DirectML |
| 网络 | WinHTTP Direct access，无系统代理；NovelAI 三个 HTTPS 探测均超时 |

## Pending Task Matrix

| ID | 状态 | 证据 |
|---|---|---|
| WIN-001 启动器测试 | DONE | `test_startup_safety` 绿；8803 一键冷启动成功 |
| WIN-002 一键首启 | DONE | 便携 runtime + `START_GALLERY.bat`；8797 被占用时换端口 |
| WIN-003 打 zip | NOT_APPLICABLE 本轮 | 未跑 `build_windows.ps1 -BundlePythonRuntime`（torch 全量包，无额外收益） |
| WIN-004 隐藏控制台 | DONE | wscript 隐藏拉起 8803 成功 |
| WIN-005 中文/长路径 | DONE | 启动器 fixture + 501 `安装's 图库` 续扫 |
| WIN-006 junction/网盘 | NOT_APPLICABLE 本轮 | 无不可逆收益；未做 |
| WIN-007 Defender | NEEDS_LOCAL_VERIFY | 本机源码启动无 SmartScreen；发行 zip 仍未签名 |
| WIN-008 DirectML | 本轮只做 Lanczos | 抽 1 张本地 PNG 2x；未走 DirectML/ONNX |
| WIN-009 Live2D | PARTIAL | 三份 model.json HTTP 200；主观手感仍未评 |
| WIN-010 真 10k/100k | DONE 只读 | `E:\aitag-mirror` 34658 works / 33230 落盘图；未拷贝、未 migrate 原库 |
| WIN-011 GPU/内存 | PARTIAL | 放大前后 nvidia-smi；不是长任务曲线 |
| WIN-012 真实付费 NAI | 本机已接 Token，出图被网络挡住 | Token DPAPI 可用；authorize 绿；NovelAI TLS 超时，未扣费 |
| WIN-013 Pixiv | NOT_APPLICABLE | 用户已延期 |
| WIN-014 旧库升级 | DONE | 副本 `aitag.db` 打开并续扫到 `unindexed=0`；未删真实库 |
| WIN-015 doctor/DPAPI | DONE | doctor 绿；Token 前缀 `dpapi:v1:`；plaintext 测试绿 |
| WIN-016 在线发现 | DONE | HTTP + 回退修复；主导航仍 8 项 |
| WIN-017 Studio 非免费确认 | DONE | 未确认 ticket 空；有底图 `free_eligible=false` |
| WIN-018 换角批量授权 | DONE | preview 无票；confirm 发票；`force_free`+底图仍要确认 |
| WIN-019 付费失败重试 | DONE 测试 / 未做真实扣费 | 现有 HMAC seal 测试锁住；未造真实失败单 |
| WIN-020 500+ 续扫 | DONE | 339 真副本 + 501 中文路径；不是用户 10k 库 |
| WIN-021 DPAPI/启动/UI | DONE | 见上；主观 UI 仍可再看一眼 |

## 旧功能 Preservation

| 能力 | 标记 | 说明 |
|---|---|---|
| 批量换角色 | EXTENDED | 授权两步，回归绿 |
| GenerationJobManager | UNCHANGED | 无第二任务生命周期 |
| unknown / billing_uncertain | UNCHANGED | 未放宽自动重试 |
| Butler receipt | UNCHANGED | 未改 receipt 语义 |
| 三库隔离 | UNCHANGED | site / codex / qqgroup 仍分库 |
| Local-first | UNCHANGED | 在线失败不标本地库不可用 |
| 路径安全 | UNCHANGED | 启动器/守卫测试绿 |
| 旧 API / WorkRef | UNCHANGED | `/api/ai_works_search` 仍返回旧字段 |
| 经典 8 项导航 | UNCHANGED | 无第 9 项 |
| Capability 执行面 | 原型 | `EXECUTION_WIRED=False` |

无未验证 AT-RISK。未做的是外部环境项，不是“没时间的架构洞”。

## 尚存 P0 / P1 / P2

- **P0：** 无
- **P1：** 本机访问 NovelAI 超时（`image.novelai.net` / `api.novelai.net`）。不是缺 Token。
- **P2：** 未打 zip；未签名；Live2D 手感；Pixiv 延期。重启后残留 `queued` 死锁已修：未发出的排队任务恢复为 `cancelled`，不再挡住新单。

## 尚未验证

- 等本机能连上 NovelAI 后再打 1 张（Token 已在隔离 DPAPI，未扣费）
- 真实 Pixiv 登录（WIN-013，本轮未做）
- `make_release.ps1` 全量 zip
- 用户主观 UI/动画

## 最终 commit

`9226c5e55bcdcd4761345f4e1404703882c9dd1f` — `fix: close Windows CI timezone, one-click log lock, and local RC holes`

## 是否建议 merge

**建议把 PR #12 从 Draft 转为可合并，合进 Upgrade `main`。**  
先等这次 push 后 GitHub `windows-latest` pytest 变绿（tzdata 应修掉 quiet-hours）。不要用 force-push。

## 是否建议 Release

**不建议现在打 GitHub Release / 对外 zip。**  
源码 RC 可以长期自用：在本工作树 `GALLERY_PORT` 避开 8797，或先停验收包。对外发行还差签名 zip 和你自愿的一次真实付费抽检。

## 回滚

```text
git fetch upgrade
git checkout cursor/cloud-top-tier-integration-f036
```

隔离数据在 `.tmp/windows-rc-data`，不影响 `pixiv-nai-gallery-full-one-click-windows/data`。
