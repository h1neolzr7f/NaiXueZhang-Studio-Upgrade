# W4 Quality Audit

C26 Worker 交付。只读核验 WEB-8（Windows 入口 / CI / 故障注入 / PENDING_LOCAL_WINDOWS）。  
本文件是建议与证据，不是 PENDING 原文，也不是能力完成声明。

规格原文 `NaiXueZhang_Studio_TopTier_Upgrade_AI_Execution_Spec-3_7323.md` 不在本 Worker 工作区。WEB-8 清单按任务四块、Lead 已落地的 WIN-001..015、以及 `AGENTS.md` / `HANDOFF_CLOUD_TO_WINDOWS.md` / `BENCHMARKS.md` / D-003 / D-005 / D-007 还原。未看到的规格句子不假装逐字引用。

## 1. 身份

| 字段 | 值 |
|---|---|
| Worker | W4 |
| 请求模型 | Grok 4.6、xhigh、Fast |
| 实际模型 | `cursor-grok-4.6-high-fast`（xhigh 在本 Cloud run 不可单独选择，已记录） |
| 仓库 | `h1neolzr7f/NaiXueZhang-Studio-Upgrade` |
| 基线分支 | `cursor/cloud-top-tier-integration-f036` @ `4d8dbea13eb166c4351c4e31f55ecc658bd40c6d` |
| 本分支 | `cursor/cloud-w4-quality-f036` |
| 本文件 | `docs/top-tier-upgrade/W4_QUALITY_AUDIT.md` |
| 运行 | https://cursor.com/agents/bc-63c67678-4907-5f7f-9b5c-ae64f2da7c6f |
| 日期 | 2026-08-15 |

## 2. 范围与未改

只新增本文件。

未改：`PENDING_LOCAL_WINDOWS.md`、生产代码、CI workflow、LICENSE、VERSION、release 脚本、Lead 独占文件、`frontend/`、Manga、真实 Token、Release、`main`。

未通过放宽付费 / unknown / 5xx / DPAPI 语义让 CI 变绿。集成分支当前 CI 为红，本审计保持该事实。

## 3. WEB-8 覆盖总表

判定：`covered` = 云端已有可重复证据；`partial` = 有入口或测试但不够验收；`queued` = 已写入 WIN 且只能本机跑；`gap` = WEB-8 需要、PENDING 未列或实现会假红/假绿。

| ID | WEB-8 项 | 判定 | 云端证据 | PENDING | 说明 |
|---|---|---|---|---|---|
| WEB-8.1 | doctor 只读入口 | covered | `scripts/doctor_windows.ps1`；`tests/test_windows_entry_aliases.py` 断言 `read-only` 且无 `pip install` | WIN-015 | doctor 只查 DPAPI 注册表键，不证明 `dpapi:v1:` 读写 |
| WEB-8.2 | setup / test / build 别名 | covered | `setup_windows.ps1`→INSTALL.bat；`run_tests_windows.ps1`→verify.ps1；`build_windows.ps1`→make_release.ps1（D-005） | WIN-001 / 003 / 015 | 别名本身未在 Windows 上执行 |
| WEB-8.3 | 一键 BAT 入口存在 | covered | `一键启动.bat` / `ONE_CLICK_START.bat` 只转调 `START_GALLERY.bat`；`tests/test_one_click_bundle.py` 静态合同 | WIN-001 / 002 | 双击、浏览器、隐藏控制台仍 queued |
| WEB-8.4 | 入口无真实 Token | partial | `check_windows_scripts.py` 扫 `nai_token` / `pst-` / `sk-` / `NOVELAI_TOKEN` | WIN-015 | 检查器把 `make_release.ps1` 的排除名单和扫描正则当凭据，见 G-001 |
| WEB-8.5 | setup_web.ps1 fail-closed | covered | `setup_web.ps1` `throw`；`tests/test_setup_web_safety.py`；doctor 也检查 | 无 WIN | 建议补 WIN，见 S-001 |
| WEB-8.6 | CI `windows-latest` + Py 3.13 | covered | `.github/workflows/tests.yml`：`windows-latest`、Python 3.13、`PYTHONUTF8=1` | 无 | 与 PENDING「优先 3.13」一致；INSTALL.bat 仍接受 3.11/3.12 |
| WEB-8.7 | CI compile + pytest + 敏感扫描 | partial | compileall → pytest（忽略 selector probe）→ `scan_sensitive.py --git-candidates --content-only` | 无 | pytest 失败则扫描永不跑；当前 PR #3 即如此 |
| WEB-8.8 | CI 与 verify / Cloud install 对齐 | gap | CI 无 JS syntax、无 `product_quality_gate`、无 `-W error`、无 `aiosqlite`；`environment.json` 有 aiosqlite | 无 | 见 S-002。不要为对齐而改业务语义 |
| WEB-8.9 | POSIX skip 不改语义 | gap | D-003 写了 `test_startup_safety` / `test_release_script_safety` / `test_plaintext_at_rest` 应 skip；三文件均无 `os.name` 守卫 | D-003 / D-007 | 只在 crawler/Pixiv import 落地了 skip。见 G-002 |
| WEB-8.10 | 故障注入：发送后超时 | partial | `tests/test_fault_injection.py` 只构造 `GenerationProviderError`；真路径在 `tests/test_nai_account_safety.py::test_read_timeout_after_request_is_marked_billing_uncertain` | 无 WIN | 专用故障文件未驱动 HTTP/job |
| WEB-8.11 | 故障注入：发送前连接失败 | partial | 专用测试只断言构造字段；未 mock connect/TLS | 无 WIN | 见 S-003 |
| WEB-8.12 | 故障注入：unknown / recovered 不重试 | partial | 专用测试调用 `partition_retry_targets`；更深覆盖在 `tests/test_generation_jobs.py` | 无 WIN | 语义未放宽，但专用文件偏薄 |
| WEB-8.13 | 故障注入：billing_uncertain 阻断 | partial | 专用测试 + `test_generation_jobs` + `test_p0_paid_security`（`no-5xx-retry` / anlas `unknown`） | WIN-012 | 5xx/429/取消/杀进程未进专用故障文件 |
| WEB-8.14 | 基准可重复且不冒充 10k/100k | partial | `scripts/bench_gallery.py` 合成内存；脚本声明 WIN-010 | WIN-010 | 默认 query 命中全部行；测试 `hits < count` 失败。见 G-003 |
| WEB-8.15 | WIN-001 BAT/PowerShell | queued | 静态合同存在；`cmd.exe` 用例无 POSIX skip | WIN-001 queued | 云端不能声称启动链已验 |
| WEB-8.16 | WIN-002 一键首跑 | queued | 无桌面/浏览器 | WIN-002 queued | |
| WEB-8.17 | WIN-003 EXE / zip | queued | `build_windows.ps1` 别名 + `test_release_script_safety` 部分静态 | WIN-003 queued | 真机打包未跑 |
| WEB-8.18 | WIN-004 隐藏控制台 / 任务栏 | queued | `scripts/launch_server.vbs` 存在 | WIN-004 queued | |
| WEB-8.19 | WIN-005 中文 / 长路径 / NTFS | queued | `test_startup_safety` 有空格+`'` 路径用例，需 cmd.exe | WIN-005 queued | |
| WEB-8.20 | WIN-006 junction / 网络盘 | queued | 无云端 NTFS junction 夹具 | WIN-006 queued | 步骤未给可复制命令 |
| WEB-8.21 | WIN-007 Defender / 签名 | queued | `BUNDLE_NOTICE.txt` 存在 | WIN-007 queued | |
| WEB-8.22 | WIN-008 DirectML / ONNX | queued | `post_pipeline.py` 仍硬编码 `E:/ai批量生图/Auto-NovelAI-Refactor` | WIN-008 queued | 无 ANR 时引擎声明未进 WIN 步骤 |
| WEB-8.23 | WIN-009 Live2D | queued | 无 Windows WebView | WIN-009 queued | |
| WEB-8.24 | WIN-010 大图库 | queued | `BENCHMARKS.md`「Required later」未全部映射到 WIN-010 | WIN-010 queued | 见 S-004 |
| WEB-8.25 | WIN-011 GPU / 内存 | queued | 本 VM 无用户 GPU | WIN-011 queued | 「mock-or-controlled」过宽 |
| WEB-8.26 | WIN-012 受控真实 NAI | queued | `tests/test_p0_paid_security.py` 锁付费闸门；真 Token 未授权 | WIN-012 blocked_needs_user | 正确保持 blocked |
| WEB-8.27 | WIN-013 受控 Pixiv | queued | 预检/取消路径有单测；无本机 Chrome 登录 | WIN-013 blocked_needs_user | |
| WEB-8.28 | WIN-014 升级 / 卸载 / 数据保留 | partial | `docs/UPGRADE.md` + `tests/test_gallery_maintenance_migration_safety.py` 只覆盖 schema/路径，不是 v1.4 `data/` 搬家 | WIN-014 queued | 备份/恢复 BAT 未进 PENDING。见 S-001 |
| WEB-8.29 | WIN-015 doctor / verify / DPAPI | queued | doctor/verify 别名存在；`test_plaintext_at_rest.py` 无 POSIX skip，Linux 会走 DPAPI 写入 | WIN-015 queued | 真机 DPAPI 仍必需 |
| WEB-8.30 | 备份 / 恢复 / Token 获取 / 爬虫启动器 | gap | `BACKUP_GALLERY.bat`、`RESTORE_GALLERY.bat`、`Get-Pixiv-Token.bat`、`start_crawl*.bat` 在一键包合同里，PENDING 无对应项 | 无 | 见 S-001 |
| WEB-8.31 | 不改业务语义让 CI 变绿 | covered（本 Worker） | 本分支不修红测 | 无 | 集成分支 CI 已红，见第 6 节 |

**汇总：** WIN-001..015 覆盖了 WEB-8 的本机桌面项。缺口在云端质量门：静态检查假红、基准测试假红、D-003 未落地、CI 与 verify 不对齐、故障注入专用文件过薄、备份/爬虫/Token 入口未进 PENDING。

## 4. Windows 入口核验

存在且被 `scripts/check_windows_scripts.py` 列为 REQUIRED：

- `INSTALL.bat`、`START_GALLERY.bat`、`ONE_CLICK_START.bat`、`一键启动.bat`
- `scripts/verify.ps1`、`doctor_windows.ps1`、`setup_windows.ps1`、`run_tests_windows.ps1`、`build_windows.ps1`、`make_release.ps1`

委托关系与 D-005 一致。doctor 只读：不装包、不写 `data/`、不用 Token。`setup_web.ps1` 永久 `throw`。

未进 REQUIRED / PENDING 的本机入口：`BACKUP_GALLERY.bat`、`RESTORE_GALLERY.bat`（`choice` 交互确认）、`Get-Pixiv-Token.bat`、`CREATE_DESKTOP_SHORTCUT.bat`、`start_crawl*.bat`、`scripts/updater.bat`。`RESTORE_GALLERY.bat` 缺少非交互恢复路径。

`INSTALL.bat` 接受 CPython 3.11–3.13；PENDING / CI / 便携 runtime 偏向 3.13。doctor 不因 3.11 失败。

## 5. CI 核验

`.github/workflows/tests.yml`：

- 触发：`push` `main` + 全部 `pull_request`
- `windows-latest`，45 分钟，Python 3.13，UTF-8
- 安装：`requirements.core.lock.txt` + pytest + langgraph + langgraph-checkpoint-sqlite（**无 aiosqlite**）
- 顺序：compileall → pytest（忽略 `test_pixiv_selector_probe.py`）→ 敏感扫描

与 `scripts/verify.ps1` 的差：verify 还跑 JS `node --check`、`check_regression_guards.js`、`product_quality_gate.py --fail-on p2`、pytest `-W error`。  
与 `.cursor/environment.json` 的差：Cloud install 多 `aiosqlite`。

敏感扫描在 pytest 之后。PR #3 @ `4d8dbea` 的 `pytest` check 失败，扫描步骤未执行。不能把「CI 扫描干净」写进该 SHA。

本 Cloud VM 上 `python3 scripts/scan_sensitive.py --git-candidates --content-only` 结果：`No sensitive literals or private publication paths found.` 这是本机扫描，不是 GitHub Actions 该 SHA 的官方结论。

## 6. 本轮实测

基线 SHA `4d8dbea`。本 Cloud VM：Linux 6.12，CPython 3.12.3。不是 Windows 生产机。

| 命令 | 结果 |
|---|---|
| `python3 -m pytest -q tests/test_fault_injection.py tests/test_windows_entry_aliases.py tests/test_setup_web_safety.py tests/test_p0_paid_security.py tests/test_local_secrets.py` | 25 passed, 3 skipped（DPAPI 本机用例） |
| `python3 -m pytest -q tests/test_windows_script_static.py tests/test_bench_gallery.py tests/test_one_click_bundle.py` | 3 failed：静态检查假红、bench hits、`cmd.exe` 缺失 |
| `python3 scripts/check_windows_scripts.py` | exit 1；`make_release.ps1` 命中 `nai_token` / `pst-` / `sk-` |
| `python3 scripts/bench_gallery.py --count 1000 --repeats 20` | 脚本可跑；`hits=1000`；p50 0.311 ms / p95 0.383 ms。**不是** 10k/100k 声明 |
| `python3 scripts/scan_sensitive.py --git-candidates --content-only` | 干净 |
| GitHub Actions `31871295683`（PR #3，windows-latest） | **3 failed, 1136 passed, 14 skipped** |

GitHub 失败三项（不得在本 Worker 修复）：

1. `tests/test_windows_script_static.py` — `make_release.ps1` 含排除文件名 `nai_token.local.json`、扫描正则 `pst-`/`sk-`、占位 `sk-abcdefghijklmnopqrstuvwxyz123456`。这是发布扫描器，不是泄露。
2. `tests/test_bench_gallery.py` — 合成行全部带 `arknights amiya`，默认 query 命中 200/200，`assertLess(hits, 200)` 失败。
3. `tests/test_nai_char_module_contracts.py` — 编译层新增 `requested_action` / `unsupported_fields` / `unknown_fields` 后，表征测试未更新。属 W1/Lead 租约，W4 不改。

## 7. 故障注入核验

`tests/test_fault_injection.py` 四例：

- 发送后超时 → `billing_uncertain` 且 `retry_safe=False`
- 发送前连接失败 → `retry_safe=True`
- `unknown` + `recovered_after_restart` → 全部 index 进入 blocked
- job `error` 且 item `billing_uncertain` → blocked

前两例只构造 `GenerationProviderError`，不经过 `nai/generate.py` 或账本。后两例调用真实 `partition_retry_targets`，有价值，但仍不是端到端注入。

已有、但未收进专用故障文件的覆盖：

- `tests/test_nai_account_safety.py`：ReadTimeout → billing_uncertain；ambiguous 失败不切第二个 token
- `tests/test_generation_jobs.py`：`http_5xx`、`no-5xx-retry`、billing_uncertain 需人工复核
- `tests/test_p0_paid_security.py`：work_order `retry_policy=no-5xx-retry`，anlas `unknown`；POSIX 拒绝明文 Token

专用文件未覆盖：HTTP 5xx 注入、429、取消、杀进程、账本 unknown 隔离、导演台 5xx 不切付费槽（后者在 `tests/test_nai_director.py`）。

## 8. PENDING_LOCAL_WINDOWS 核验

WIN-001..015 条数、能力映射、责任角色、queued / blocked_needs_user 状态完整。WIN-012 / WIN-013 保持 `blocked_needs_user` 正确。

已列但偏弱：

- WIN-006 无精确命令
- WIN-008 依赖「本地超分工作已存在」，且未要求记录「无 ANR 时的引擎名」
- WIN-010 未吸收 `BENCHMARKS.md` 的冷启动 / 1k·10k 导入 / 增量 / 缩略图 / 10·100·300 任务 / 断线取消崩溃 / 重复副作用 / 60 图后处理 / 首次安装到首次出图 / PNG 往返
- WIN-011 允许 mock，容易被写成已验
- WIN-014 未包含 `BACKUP_GALLERY.bat` / `RESTORE_GALLERY.bat` 往返
- WIN-015 未要求 doctor 与 `test_plaintext_at_rest` 对同一枚 Token 交叉证明 `dpapi:v1:`

D-003 声称的 POSIX skip 未写进三份启动/发布/明文测试。不要把「云端 pytest 全绿」写进交接。

## 9. 建议 WIN（不要直接改 PENDING_LOCAL_WINDOWS.md）

供 Lead 采纳后写入 PENDING。编号仅建议。

### S-001 / 建议 WIN-016 备份恢复与凭据入口

- 能力：recover / 数据和付费安全
- 为何云端不能验：`RESTORE_GALLERY.bat` 用 `choice`；Token 获取要本机浏览器
- 相关：`BACKUP_GALLERY.bat`、`RESTORE_GALLERY.bat`、`Get-Pixiv-Token.bat`、`gallery_snapshot.py`
- 步骤：备份不含凭据；恢复不覆盖 `nai_token` / Pixiv accounts；`Get-Pixiv-Token.bat` 不在控制台打印 refresh token，落盘为 `dpapi:v1:`
- 角色：W4 / local Lead

### S-001b / 建议 WIN-017 爬虫启动器

- 能力：ingest
- 相关：`start_crawl.bat`、`start_crawl_all.bat`、`start_crawl.ps1`、`tests/test_pixiv_default_crawler_contract.py`
- 步骤：确认默认启动器不拉起已废弃 upstream crawler；空主图库拒绝启动（已有单测，需本机再点一次）

### S-002 / 建议 WIN-018 记录 CI 与 verify 差集

- 能力：文档与可验证性
- 相关：`.github/workflows/tests.yml`、`scripts/verify.ps1`、`.cursor/environment.json`
- 步骤：在 HANDOFF 写明 CI 子集；本机 `run_tests_windows.ps1` 不得用 CI 绿代替 verify 绿
- 不要：为对齐 CI 而删 `product_quality_gate` 或放宽 `-W error`

### S-003 / 建议 WIN-019 加深故障注入（仍无真实 Token）

- 能力：gen.cancel_balance_error / recover.generation_unknown
- 相关：`tests/test_fault_injection.py`、`nai/generate.py`、`generation_jobs.py`
- 步骤：用 mock HTTP 注入 ReadTimeout / connect fail / 5xx / 429，断言账本与 `can_retry`；不要为绿测改 `retry_safe`
- 角色：W4；可在云端做，不必等 Windows

### S-004 / 建议 WIN-020 展开 WIN-010 基准清单

把 `BENCHMARKS.md`「Required later」逐条变成 WIN-010 子项，同一台 Windows 机器、同一数据集、记录 CPU/RAM/GPU。

### S-005 / 建议修正（非新 WIN，给 Lead 修 CI 假红）

不要改业务语义。建议由现租约所有者修：

1. `scripts/check_windows_scripts.py`：对 `make_release.ps1` 的排除名单 / 扫描正则 / 已知占位符放行，或改为扫「赋值后的凭据字面量」。W4 本轮不改，避免与 Lead 冲突。
2. `scripts/bench_gallery.py` / `tests/test_bench_gallery.py`：合成数据或默认 query 必须能区分命中与未命中。属 W2/W4 共享脚本；本轮不改。
3. `tests/test_nai_char_module_contracts.py`：把新编译字段纳入表征集合。属 W1。
4. D-003：给 `test_startup_safety.py` / `test_release_script_safety.py` / `test_plaintext_at_rest.py` / `test_one_click_bundle.py` 的 cmd/powershell/DPAPI 用例加 `os.name == "nt"` skip。只 skip，不改启动或加密语义。

## 10. 不得声称

- 未声称顶尖或 Phase 0 质量门已关
- 未声称 Windows 一键 / DPAPI / Defender / Live2D / 大图库已验
- 未声称集成分支 CI 绿
- 未声称 10k/100k 数字
- 未使用真实 NAI / Pixiv Token
- 未连接 Manga
- 未把故障注入四例当成端到端付费路径证明

## 11. Lead 裁决

1. 是否采纳 S-001..S-004 写入 PENDING（W4 不直接改）。
2. 假红三项由谁在集成分支修；修时禁止放宽 `force_free` / 5xx / unknown / DPAPI。
3. 敏感扫描是否应先于或并行于 pytest，避免红测挡住发布扫描。
4. `check_windows_scripts.py` 是否纳入 CI；纳入前必须先消假红。

## 12. 回滚

```text
git checkout cursor/cloud-top-tier-integration-f036
# 或删除 cursor/cloud-w4-quality-f036
```

不 force-push，不合 `main`。

## 13. 下一步

Lead 审阅本文件。本机 Windows 仍从 HANDOFF 第 14–15 节开始：`doctor_windows.ps1` 然后 `run_tests_windows.ps1 -SkipBrowserTests`。W4 本轮不再改其他文件。
