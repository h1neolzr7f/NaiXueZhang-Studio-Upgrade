# Nai学长工作室 · 升级版说明

本文说明 **升级版仓库** 与 **稳定版 v1.4.0** 的关系、已落地的能力，以及使用方式。它不是许可证，也不改变 [MIT License](../LICENSE) 授予的代码使用权。

## 两条产品线

| 名称 | 仓库 | 给谁用 |
|---|---|---|
| 稳定版 v1.4.0 修复版 | [h1neolzr7f/NaiXueZhang-Studio](https://github.com/h1neolzr7f/NaiXueZhang-Studio) | 需要官方一键 Windows 包、要对哈希的用户 |
| 升级版 v2.0.0 | [h1neolzr7f/NaiXueZhang-Studio-Upgrade](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade) | 要从源码跟进 `/app` 工作区与模块拆分的用户 |

升级版从稳定版的工程与付费闸门出发，把常用工具收到同一套工作区，并拆开过大的后端模块。它**不是**另一个产品名，也**不是**官方对 pixiv / NovelAI 的授权版本。

## 不要混用的几件事

1. **一键 zip 仍以稳定版 Releases 为准。** 升级版仓库当前发布的是源码，没有另打官方便携包。
2. **不要把 Token、图库、`data/` 提交进 Git。** 两条线的 `.gitignore` 规则相同。
3. **付费出图规则没有放宽。** 工作区只是换了界面，生成、导演台、批量换角仍走原来的任务与预检接口。
4. **经典 HTML 没有删除。** `/`、`/studio`、`/remix` 等书签仍可用；主导航指向 `/app`。

## 界面与导航

升级版启动后，建议使用：

```text
http://127.0.0.1:8797/app
```

主导航固定 8 项：

1. 图库 `/app`
2. 生成库 `/app/generated`
3. 工作台 `/app/studio`
4. 小镜 `/app/butler`
5. 换角 `/app/remix`
6. 爬虫 `/app/progress`
7. 分类 `/app/tags`
8. 发布 `/app/pixiv`

工作区内还有导演台、后处理、运营、合规。设置仍可通过工作区或经典 `/settings` 打开。

## 相对 v1.4.0 的功能

### 工作区

- 图库：关键词、Prompt、分组、时间、收藏 / 待生成队列、详情进工作台或换角。
- 工作台：导入作品、参数、份数 1–8、冻结快照、默认免费档、净化标签。
- 生成库：分组、回收站（公开字段）、恢复、用来源再出图。
- 换角：单张抽出角色槽并套预设；批量读取待生成队列，先 `/api/plugin/char-swap/batch/preview`，确认后再 `batch/run`。
- 分类：NAI 标签分面与作品筛选，进入工作台 / 换角。
- 发布：账号、浏览器登录、上传页探测（不上传文件）、按生成组上传、一键起号。打开的是本机 Chrome，不是 Anlas 扣费。
- 运营：只读健康检查与产品定位。
- 合规：责任声明、作者黑名单（默认只拦爬取）、拦截作品。删除本地文件仍走经典合规页并二次确认。

### 后端结构

- `nai_api.py` → `nai/`（tokens、generate、director、jobs）
- `butler_service.py` → `butler/`（planning、execute、chat 等）
- `butler/workflow.py` 为 facade；运行时在 `workflow_runtime.py`，长循环在 `workflow_executors.py`
- 数据目录通过 `paths.DeferredDataPath` 在调用时解析，避免 import 时冻死测试夹具

### 前端工程

- 源码在 `frontend/`（Vite 6 + React 18 + TypeScript）
- 构建命令：`npm run workspace:build`
- 运行时只加载 `web/app/workspace.js`，**不需要**安装 Node
- 工作区禁止裸 `fetch(`，由 `web/shared/api-client.js` 携带会话令牌

## 付费与安全（升级版未改口）

- 生成请求冻结点击当时的 comment；
- 默认 `force_free`；
- HTTP 5xx 有响应时不自动重试；
- `unknown` / `recovered_after_restart` 不视为「没扣费」；
- 导演台必须预检通过后再确认启动；
- 空主图库时拒绝启动采集；
- 会话令牌拿不到则写接口 fail-closed；
- 非 Windows 无法 DPAPI 时拒绝把密钥写入 `data/`。

## 从稳定版迁到升级版源码

1. 备份整个 `data/`（图库、数据库、加密凭据都在这里）。
2. 克隆本仓库，建立 venv，安装 `requirements.core.lock.txt`。
3. 将稳定版的 `data/` 放到升级版目录（或配置相同的数据目录）。
4. 启动 `python server.py`，打开 `/app` 确认图库仍在。
5. 不要把两套程序同时写同一个正在使用的数据库。

数据库 schema 若需迁移，启动时会按现有逻辑升级；不要手工降级 `PRAGMA user_version`。

## 构建工作区前端

仅在修改 `frontend/src` 之后需要：

```powershell
npm run workspace:build
python scripts/asset_versions.py
```

请在仓库根目录执行 `asset_versions.py`，不要在 `frontend/` 里执行。

## 测试范围（升级版额外）

除稳定版已有的付费 / 安全回归外，升级版还覆盖：

- `tests/test_workspace_stack.py`：工作区包、主题顺序、API 针、禁止裸 fetch、主导航 `/app/tags`
- `tests/test_architecture_split.py`：facade 与 executors 拆分契约、`DATA_DIR` 延迟解析
- `tests/test_site_nav_ui.py`：主导航恰好 8 项

Playwright 选择器探测 `tests/test_pixiv_selector_probe.py` 需要本机 Chromium，默认不纳入 CI。
