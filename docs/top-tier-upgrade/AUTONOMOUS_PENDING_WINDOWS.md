# Autonomous pending Windows

Updated: 2026-08-16. Windows Final QA closed the local-completable items. See `WINDOWS_RC_REPORT.md`.

Remaining user-gated / optional: WIN-012 paid NAI, WIN-013 Pixiv, WIN-003 signed zip, WIN-010 real 10k/100k, subjective Live2D/GPU.

Do not treat Linux 10k/100k synthetic numbers as Windows results.

## WIN-016 Classic gallery「在线发现」

- Why cloud cannot verify: no real desktop chrome/layout, no real provider
- Where: `/` → 数据域「在线发现」(`web/online-discover.js`)
- Steps: 打开图库 → 点「在线发现」→ 搜索 →「收藏（不下载）」→「加入我的图库」→ 应跳到 `/studio?from=<id>&gallery=codex`
- Expected: 收藏不产生本地文件；入库后作品在自选库；主导航仍是 8 项
- Failure: 面板不出现、搜索失败却把本地图库标成不可用、入库后找不到图

## WIN-017 Studio 非免费确认

- Why cloud cannot verify: no real Anlas / token
- Where: `/studio` 经典工作台与 `/app` 工作区 Studio
- Steps: 选一张带底图的 img2img → 点生成 → 应先出现确认（此时还没有可用 ticket）→ 取消则不出图 → 确认后才签发 ticket 并入队
- Expected: 未确认的 `/api/nai/authorize` 响应里 `ticket` 为空；确认后才有 ticket；无 token 时是缺 token，不是静默成功
- Failure: 不确认就出图，或确认后 403

## WIN-018 换角批量授权

- Why cloud cannot verify: real images + token
- Where: 经典换角队列「批量生成」、工作区 `/remix`
- Steps: 队列里放 img2img 目标 → 批量生成 → 确认非免费 → 任务出现
- Expected: 预检仍零费用；`force_free` 开着但有底图时仍要确认（`free_eligible=false`）
- Failure: 直接 403，或跳过确认

## WIN-019 付费部分失败后重试

- Why cloud cannot verify: no real paid batch
- Steps: 用户自愿的一小批付费任务中让一项失败（非 `unknown` / 非 `billing_uncertain`）→ 点重试
- Expected: 不要求再贴一张新 ticket；`unknown` / `billing_uncertain` 仍不能自动重试
- Failure: 重试 403，或 uncertain 被重放

## WIN-020 旧图库升级后索引续扫

- Why cloud cannot verify: no user 10k/100k library
- Steps: 用自己的旧库启动 → 触发增量索引直到 `unindexed=0` → 抽查 501 张以上的库不会停在第一页
- Expected: 不丢页；重启后可从 cursor 继续
- Failure: 只索引 500、或把未扫到的页标成 stale 删掉

## WIN-021 DPAPI / 一键启动 / 真机手感

- 沿用 WIN-001、WIN-002、WIN-015
- 本轮没有改启动器，但仍要在 Windows 上走一遍，确认新前端资源 `?v=` 能加载 `online-discover.js`

## 用户最短路径（第一次接手）

1. 一键启动，打开 `http://127.0.0.1:8797/`
2. 旧图库还在，搜索可用
3. 点「在线发现」走一遍收藏 / 入库（合成源，不连外网付费）
4. 工作台：免费 txt2img 若有 token；img2img 看确认框（可取消）
5. 换角：零费用预检 + 一次确认后的批量（可取消）
6. 若愿意：WIN-012 一次受控真实 NAI；Pixiv 仍按 WIN-013 跳过除非你改主意

反馈时请写：哪一页、点了什么、期望、实际、是否付费/是否旧库。不要只说「不好用」。
