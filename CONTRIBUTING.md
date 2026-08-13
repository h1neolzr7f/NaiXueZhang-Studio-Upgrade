# Contributing to Nai学长工作室（升级版）

感谢你愿意改进这个项目。本仓库是升级版源码主干；稳定版一键包仍在 [`NaiXueZhang-Studio`](https://github.com/h1neolzr7f/NaiXueZhang-Studio)。项目欢迎工程、性能、可用性、文档与测试方面的贡献，同时坚持本地优先、来源可追踪和不提交私人数据的原则。

## 适合贡献的内容

- 可复现的 Bug 修复与回归测试；
- 大图库、SQLite、缓存和任务队列性能优化；
- Prompt、角色换角、标签分类和生成工作流改进；
- 本地安全、凭据保护、更新与打包可靠性；
- UI 可用性、无障碍、文档与翻译；
- 不依赖用户私人数据的通用适配器与工具。

## 提交前准备

1. 从 `main` 创建功能分支；
2. 不要提交 `data/`、图库、数据库、Cookie、Token、日志或私人截图；
3. 新行为应附带测试，修复应尽量附带失败用例；
4. 保持现有功能兼容，避免把高级能力静默改成受限版本；
5. 涉及第三方平台时，使用中性、准确的描述，不宣称官方授权。

## 本地验证

```powershell
python -m pip install -r requirements.core.lock.txt pytest
python -m pytest -q --ignore=tests/test_pixiv_selector_probe.py
python scripts/scan_sensitive.py
```

不要对整个工作区执行 `python -m compileall .`，它会走进本地 `runtime/`。需要编译检查时排除该目录：

```powershell
python -m compileall -q -x "runtime|\.venv|node_modules|data" .
```

修改 `frontend/` 时：

```powershell
npm run workspace:build
python scripts/asset_versions.py
```

修改经典页 JavaScript 时额外运行：

```powershell
node --check web/shared/site-nav.js
node --check web/compliance.js
```

## Pull Request 要求

PR 描述应包含：

- 问题与影响；
- 修改方案；
- 已运行的测试；
- UI 变化截图（不得含私人素材或凭据）；
- 兼容性、迁移或回滚说明。

建议保持一个 PR 只解决一个主题。大型重构先提交 Issue 说明边界和迁移策略。

## 数据与版权

不要提交：

- 从第三方平台下载的完整图片或作品集合；
- 未获授权的测试数据；
- 真实 NovelAI Token、Pixiv refresh token、Cookie、API Key；
- 含用户名、家庭目录、浏览器档案或本地路径的日志；
- 为绕过验证码、访问控制、限流或封禁而设计的补丁。

测试素材应由代码生成、采用最小虚构数据，或使用明确允许再分发的资源。

## 安全问题

请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中披露可利用细节或凭据。

## 行为准则

参与即表示同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
