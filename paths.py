"""将 config 中的相对路径解析为基于项目根目录的绝对路径。"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from os import PathLike
from pathlib import Path
from typing import Any

_DATA_DIR_CACHE: Path | None = None


def project_root() -> Path:
    """Runtime data root. In a frozen bundle this is the directory that holds
    the executable (writable); in source mode it is the project directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_web_dir() -> Path | None:
    """Directory of bundled web assets inside a PyInstaller onefile bundle."""
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        candidate = Path(meipass) / "web"
        if candidate.is_dir():
            return candidate
    return None


def resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def canonical_path(path: Path | str) -> Path:
    """Expand 8.3 short names before containment checks.

    ``Path.resolve()`` on Windows can leave ``C:\\Users\\RUNNER~1\\...`` while a
    child path expands to ``C:\\Users\\runneradmin\\...``. ``relative_to`` then
    falsely reports an escape. ``os.path.realpath`` makes both sides comparable
    without changing on-disk casing used for stored relative paths.
    """

    return Path(os.path.realpath(os.fspath(path)))


def path_is_within(child: Path | str, parent: Path | str) -> bool:
    """True when *child* is *parent* or a descendant after canonicalization."""

    try:
        child_c = os.path.normcase(os.path.realpath(os.fspath(child)))
        parent_c = os.path.normcase(os.path.realpath(os.fspath(parent)))
        Path(child_c).relative_to(Path(parent_c))
        return True
    except (OSError, ValueError):
        return False


def relative_to_canonical(child: Path | str, parent: Path | str) -> str:
    """POSIX-relative path from *parent* to *child*, using realpath forms."""

    child_c = canonical_path(child)
    parent_c = canonical_path(parent)
    if not path_is_within(child_c, parent_c):
        raise ValueError(f"{child_c} is not in the subpath of {parent_c}")
    return child_c.relative_to(parent_c).as_posix()


def normalize_config(config: dict, root: Path | None = None) -> dict:
    root = root or project_root()
    out = dict(config)
    for key in ("data_dir", "web_dir"):
        if key in out and out[key]:
            out[key] = str(resolve_path(root, out[key]))
    return out


class DeferredDataPath(PathLike[str]):
    """Path that resolves through a factory on each use.

    Import-time ``DATA_DIR = data_dir()`` freezes the location for the process.
    Tests and portable bundles can relocate the data root after import; this
    proxy keeps production lookups live while still allowing
    ``module.TOKEN_PATH = tmp / "file.json"`` to replace the proxy entirely.
    """

    def __init__(self, factory: Callable[[], Path]) -> None:
        object.__setattr__(self, "_factory", factory)

    def _path(self) -> Path:
        return Path(self._factory())

    def __fspath__(self) -> str:
        return str(self._path())

    def __truediv__(self, other: Any) -> Path:
        return self._path() / other

    def __rtruediv__(self, other: Any) -> Path:
        return Path(other) / self._path()

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return f"DeferredDataPath({self._path()!r})"

    def __eq__(self, other: object) -> bool:
        try:
            return self._path() == Path(other)  # type: ignore[arg-type]
        except TypeError:
            return NotImplemented

    def __hash__(self) -> int:
        return hash(self._path())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._path(), name)


def data_dir(root: Path | None = None) -> Path:
    """读取 config.json 的 data_dir（已解析为绝对路径）。"""
    global _DATA_DIR_CACHE
    if _DATA_DIR_CACHE is not None:
        return _DATA_DIR_CACHE
    root = root or project_root()
    config_path = root / "config.json"
    if config_path.exists():
        cfg = normalize_config(
            json.loads(config_path.read_text(encoding="utf-8")),
            root,
        )
        _DATA_DIR_CACHE = Path(cfg["data_dir"])
    else:
        _DATA_DIR_CACHE = (root / "data").resolve()
    return _DATA_DIR_CACHE


def normalize_image_relative(path: str | None) -> str:
    """把 work_images.local_path 统一为相对 images_dir 的形式。

    历史写入存在两种约定：intake 写 ``NAI/...``（相对 images_dir），
    旧 crawler 写 ``images/NAI/...``（相对 data_dir）。读取侧一律先过这个
    函数再拼接 images_dir；新写入必须直接使用本函数输出的规范形式。
    """

    relative = str(path or "").replace("\\", "/").lstrip("/")
    for prefix in ("data/images/", "images/"):
        if relative.startswith(prefix):
            relative = relative[len(prefix) :]
            break
    return relative


def seed_data_file(name: str) -> Path:
    """Prefer the active data_dir copy, else the package seed under <root>/data/."""
    filename = Path(str(name)).name
    active = data_dir() / filename
    if active.is_file():
        return active
    bundled = project_root() / "data" / filename
    return bundled if bundled.is_file() else active


def storage_paths(config: dict, root: Path | None = None) -> dict[str, str]:
    """返回图库相关目录的绝对路径（供进度页/图库页展示）。"""
    root = root or project_root()
    cfg = normalize_config(config, root)
    data_dir = Path(cfg["data_dir"])
    return {
        "project_root": str(root.resolve()),
        "data_dir": str(data_dir),
        "images_dir": str(data_dir / "images"),
        "database_path": str(data_dir / "aitag.db"),
        "generated_dir": str(data_dir / "generated"),
    }