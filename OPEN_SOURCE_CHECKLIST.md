# Open Source Release Checklist

在将仓库切换为 Public 或发布新版本前，逐项确认。

## Secrets and local data

- [ ] `python scripts/scan_sensitive.py` 通过
- [ ] 仓库中不存在 Token、refresh token、Cookie、API Key 或账号文件
- [ ] 不存在真实图库、生成历史、数据库、浏览器档案或缓存
- [ ] 不存在用户名、家庭目录、本地绝对路径和调试转储
- [ ] `data/`、`logs/`、`reports/`、`backups/` 和 `_trash/` 已被忽略
- [ ] 发布包用干净目录重新构建，而不是直接压缩开发目录

## License and rights

- [ ] `LICENSE`、README、发行包说明和 Release 文案保持一致
- [ ] 代码版权声明不暗示拥有第三方图片、Prompt、角色或商标
- [ ] README 顶部包含非官方关系与责任提示
- [ ] `DISCLAIMER.md`、`RESPONSIBLE_USE.md`、`SECURITY.md` 可访问
- [ ] 测试、截图和示例素材拥有明确的再分发权利

## Security and reliability

- [ ] `python -m pytest -q` 通过
- [ ] `python scripts/product_quality_gate.py --fail-on p1` 通过
- [ ] Token 与 refresh token 明文落盘回归测试通过
- [ ] localhost 写操作缺少会话令牌时返回 403
- [ ] 更新清单与更新包均使用 HTTPS，SHA-256 必填且格式有效
- [ ] 作者清理会移动文件到回收区，并同步清理数据库索引
- [ ] 路径越界测试通过

## Public repository presentation

- [ ] 仓库描述清楚说明这是升级版源码主干，并链到稳定版 Releases
- [ ] Topics 至少包含 `novelai`、`aigc`、`fastapi`、`local-first`、`image-management`
- [ ] README 的下载、Roadmap 和贡献链接有效
- [ ] 至少准备 3 张脱敏截图或 1 个短 Demo GIF
- [ ] Issues、Discussions 或安全报告渠道已配置
- [ ] 当前公开版本标记正确（稳定版一键包为 v1.4.0 修复版；本升级版仓库为 v2.0.0 源码主干，不要把未发布的 zip 写成正式 Release）

## Release provenance

- [ ] Release 记录版本号、Commit SHA 与构建日期
- [ ] 每个发行包提供 SHA-256
- [ ] 发行包不包含源图库、私人配置和运行数据
- [ ] 从 Release 下载后在干净 Windows 用户环境完成启动冒烟测试
- [ ] 非官方修改版与官方构建的识别方式已写入 Release 文案

完成后建议先创建 Draft Release，由另一台机器或另一位测试者做最后检查，再正式公开。
