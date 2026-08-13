## 为什么

说明用户或维护者会碰到的问题，以及不改会怎样。

## 改了什么

只写这次 diff 的净变化。涉及付费出图时，写明是否仍满足：冻结快照、默认 `force_free`、5xx 不自动重试、`unknown` 不重试。

## 检查

- [ ] 未提交 `data/`、Token、Cookie、图库或私人截图
- [ ] 相关测试已更新或说明为何不必加
- [ ] 若改了 `frontend/`：已运行 `npm run workspace:build` 与 `python scripts/asset_versions.py`
- [ ] 不是在添加绕过验证码、限流或访问控制的能力
