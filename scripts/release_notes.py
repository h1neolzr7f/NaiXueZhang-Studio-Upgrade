# -*- coding: utf-8 -*-
"""Generate official release notes with provenance/security markers.

Usage:
    python scripts/release_notes.py VERSION ZIP_PATH

Prints markdown notes embedding: version, commit hash, zip SHA-256,
official-build marker and the responsibility disclaimer pointer.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def commit_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("zip_path")
    args = parser.parse_args()

    zip_path = Path(args.zip_path).resolve()
    if not zip_path.is_file():
        print(f"zip not found: {zip_path}", file=sys.stderr)
        return 2

    digest = sha256_of(zip_path)
    commit = commit_hash()
    notes = f"""## {args.version} 官方构建（Official Build）

> **非官方项目与使用责任提示**：本项目与 pixiv Inc.、NovelAI 及其他第三方平台不存在隶属、授权或合作关系。使用者应自行确认其访问、下载、处理和发布行为符合适用法律、平台规则及第三方权利要求。项目维护者不鼓励、不指导，也不为绕过访问控制、干扰平台运行、未经授权的数据采集或侵权传播提供支持。详见 DISCLAIMER.md 与 RESPONSIBLE_USE.md。

### 构建信息

- 版本：{args.version}
- Commit：`{commit}`
- 发布包 SHA-256：`{digest}`
- License：MIT

### 校验方式

```powershell
Get-FileHash -Algorithm SHA256 .\\{zip_path.name}
```

下载后请核对上方 SHA-256。**任何其他来源、其他哈希的发布包均非本项目维护者发布**，请勿运行来历不明的修改版。

### 官方仓库

- 稳定版发布页：https://github.com/h1neolzr7f/NaiXueZhang-Studio/releases
- 升级版源码：https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade
- 反馈：请提交 Issue（避免在公开渠道披露凭据等敏感信息）
"""
    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
