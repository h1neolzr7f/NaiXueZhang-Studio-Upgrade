"""本地采集进程的安全查找、停止与启动（Windows）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
CRAWLER_SCRIPT = ROOT / "crawler.py"
QQ_CRAWLER_SCRIPT = ROOT / "crawler_qq.py"
PIXIV_CRAWLER_SCRIPT = ROOT / "pixiv_nai_crawler.py"
SUPERVISOR_SCRIPT = ROOT / "run_crawl_background.ps1"
LOG_DIR = ROOT / "logs"
PIXIV_CRAWLER_LOCK_NAME = "pixiv_nai_crawler.lock"

_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_PROCESS_CACHE_TTL_SEC = 8.0
_process_cache: dict[str, tuple[float, list[int]]] = {}


@dataclass(frozen=True)
class _OwnedProcess:
    pid: int
    create_time: float
    script_path: Path


def invalidate_process_cache() -> None:
    _process_cache.clear()


def data_dir() -> Path:
    """Resolve the configured data directory (same rules as the crawler CLI)."""

    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        configured = Path(str(config.get("data_dir") or "data"))
        return (
            configured if configured.is_absolute() else (ROOT / configured).resolve()
        )
    except (OSError, ValueError, TypeError):
        return (ROOT / "data").resolve()


def pixiv_crawler_lock_path(root: Path | None = None) -> Path:
    if root is not None and Path(root).resolve() != ROOT:
        try:
            config = json.loads(
                (Path(root) / "config.json").read_text(encoding="utf-8")
            )
            configured = Path(str(config.get("data_dir") or "data"))
            base = (
                configured
                if configured.is_absolute()
                else (Path(root) / configured).resolve()
            )
        except (OSError, ValueError, TypeError):
            base = (Path(root) / "data").resolve()
        return base / PIXIV_CRAWLER_LOCK_NAME
    return data_dir() / PIXIV_CRAWLER_LOCK_NAME


def pid_alive(pid: int) -> bool:
    try:
        return int(pid) > 0 and bool(psutil.pid_exists(int(pid)))
    except Exception:
        return False


class CrawlerLockHeld(RuntimeError):
    """Raised when another live process already holds the crawler lock."""

    def __init__(self, pid: int) -> None:
        super().__init__(f"pixiv crawler lock already held by pid {pid}")
        self.pid = pid


class CrawlerFileLock:
    """Cross-process single-instance guard based on an O_EXCL lock file.

    Windows has no fcntl; ``os.open(O_CREAT | O_EXCL)`` is atomic enough here.
    A lock whose recorded pid is dead (or whose content is unparsable and
    stale) is reclaimed by the next contender.
    """

    # A just-created lock file may briefly be empty while the owner writes its
    # pid; only reclaim unparsable locks older than this grace window.
    _STALE_GRACE_SEC = 30.0

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    def holder_pid(self) -> int:
        try:
            return int(self.path.read_text(encoding="ascii", errors="ignore").strip())
        except (OSError, ValueError):
            return 0

    def _reclaim_stale(self) -> bool:
        pid = self.holder_pid()
        if pid > 0:
            if pid_alive(pid):
                return False
        else:
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                return True
            if age < self._STALE_GRACE_SEC:
                return False
        try:
            self.path.unlink()
        except OSError:
            return False
        return True

    def acquire(self) -> "CrawlerFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                fd = os.open(
                    str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
            except FileExistsError:
                if self._reclaim_stale():
                    continue
                raise CrawlerLockHeld(self.holder_pid()) from None
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            except Exception:
                os.close(fd)
                self.path.unlink(missing_ok=True)
                raise
            self._fd = fd
            return self
        raise CrawlerLockHeld(self.holder_pid())

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        # Only remove the lock we own; a reclaimer may have replaced it.
        if self.holder_pid() == os.getpid():
            self.path.unlink(missing_ok=True)

    def __enter__(self) -> "CrawlerFileLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _cached_pids(key: str, loader) -> list[int]:
    now = time.time()
    cached = _process_cache.get(key)
    if cached and now - cached[0] < _PROCESS_CACHE_TTL_SEC:
        return list(cached[1])
    pids = loader()
    _process_cache[key] = (now, list(pids))
    return pids


def _canonical_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _cmdline_owned_by(arguments: list[str], script_path: Path) -> bool:
    """Accept only an absolute command argument equal to our exact script."""
    target = _canonical_path(script_path)
    for argument in arguments:
        candidate = str(argument or "").strip().strip('"')
        if not candidate or not Path(candidate).is_absolute():
            continue
        if _canonical_path(candidate) == target:
            return True
    return False


def _list_owned_processes(
    script_path: Path,
    *,
    executable_names: set[str],
) -> list[_OwnedProcess]:
    owned: list[_OwnedProcess] = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            name = str(process.info.get("name") or "").lower()
            if name not in executable_names:
                continue
            arguments = [str(item) for item in (process.info.get("cmdline") or [])]
            if not _cmdline_owned_by(arguments, script_path):
                continue
            owned.append(
                _OwnedProcess(
                    pid=int(process.info["pid"]),
                    create_time=float(process.info["create_time"]),
                    script_path=script_path,
                )
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, TypeError, ValueError):
            continue
    return owned


def _list_crawler_processes_uncached() -> list[_OwnedProcess]:
    return _list_owned_processes(
        CRAWLER_SCRIPT,
        executable_names={"python.exe", "pythonw.exe"},
    )


def _list_supervisor_processes_uncached() -> list[_OwnedProcess]:
    return _list_owned_processes(
        SUPERVISOR_SCRIPT,
        executable_names={"powershell.exe", "pwsh.exe"},
    )


def _list_qq_crawler_processes_uncached() -> list[_OwnedProcess]:
    return _list_owned_processes(
        QQ_CRAWLER_SCRIPT,
        executable_names={"python.exe", "pythonw.exe"},
    )


def _list_pixiv_crawler_processes_uncached() -> list[_OwnedProcess]:
    return _list_owned_processes(
        PIXIV_CRAWLER_SCRIPT,
        executable_names={"python.exe", "pythonw.exe"},
    )


def _list_crawler_pids_uncached() -> list[int]:
    return [process.pid for process in _list_crawler_processes_uncached()]


def _list_supervisor_pids_uncached() -> list[int]:
    return [process.pid for process in _list_supervisor_processes_uncached()]


def _list_qq_crawler_pids_uncached() -> list[int]:
    return [process.pid for process in _list_qq_crawler_processes_uncached()]


def _list_pixiv_crawler_pids_uncached() -> list[int]:
    return [process.pid for process in _list_pixiv_crawler_processes_uncached()]


def list_crawler_pids() -> list[int]:
    return _cached_pids("crawler", _list_crawler_pids_uncached)


def list_supervisor_pids() -> list[int]:
    return _cached_pids("supervisor", _list_supervisor_pids_uncached)


def list_qq_crawler_pids() -> list[int]:
    return _cached_pids("qqgroup", _list_qq_crawler_pids_uncached)


def list_pixiv_crawler_pids() -> list[int]:
    return _cached_pids("pixiv", _list_pixiv_crawler_pids_uncached)


def crawler_running() -> bool:
    """Compatibility status for the product's primary Pixiv NAI intake."""
    return bool(list_pixiv_crawler_pids())


def _kill_owned_processes(processes: list[_OwnedProcess]) -> list[int]:
    stopped: list[int] = []
    for identity in processes:
        try:
            process = psutil.Process(identity.pid)
            if abs(process.create_time() - identity.create_time) > 0.001:
                continue
            if not _cmdline_owned_by(process.cmdline(), identity.script_path):
                continue
            process.kill()
            try:
                process.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
            stopped.append(identity.pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.TimeoutExpired):
            continue
    return stopped


def stop_crawler_processes() -> dict[str, list[int]]:
    """Stop primary Pixiv intake and clean up any legacy processes left running."""
    invalidate_process_cache()
    crawler_processes = _list_crawler_processes_uncached()
    supervisor_processes = _list_supervisor_processes_uncached()
    pixiv_processes = _list_pixiv_crawler_processes_uncached()
    stopped = {
        "crawler_pixiv": _kill_owned_processes(pixiv_processes),
        "crawler_legacy": _kill_owned_processes(crawler_processes),
        "supervisor_legacy": _kill_owned_processes(supervisor_processes),
    }
    invalidate_process_cache()
    return stopped


def _spawn_detached_ps(
    *,
    file_path: str,
    arg_list: list[str],
    title: str,
) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in title.strip().lower()
    ).strip("-") or "crawler"
    out_path = LOG_DIR / f"{safe_title}.out.log"
    err_path = LOG_DIR / f"{safe_title}.err.log"
    out = out_path.open("a", encoding="utf-8")
    err = err_path.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [file_path, *arg_list],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        invalidate_process_cache()
        return int(process.pid)
    finally:
        out.close()
        err.close()


def _crawler_phase() -> str:
    try:
        import json

        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        phase = str(cfg.get("crawler_phase", "all")).strip() or "all"
        if phase in {"all", "search", "detail", "preview"}:
            return phase
    except Exception:
        pass
    return "all"


def _legacy_site_crawler_enabled() -> bool:
    try:
        import json

        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return bool(cfg.get("legacy_aitag_crawler_enabled", False))
    except Exception:
        return False


def _start_legacy_site_crawler(*, use_supervisor: bool = True) -> dict[str, object]:
    """Migration-only implementation; no public control path calls this."""
    invalidate_process_cache()
    crawler_pids = _list_crawler_pids_uncached()
    supervisor_pids = _list_supervisor_pids_uncached()
    existing = crawler_pids or supervisor_pids
    if existing:
        return {
            "mode": "existing",
            "pid": existing[0],
            "pids": existing,
            "phase": _crawler_phase(),
            "already_running": True,
        }
    if not _legacy_site_crawler_enabled():
        return {
            "mode": "disabled",
            "phase": _crawler_phase(),
            "already_running": False,
            "started": False,
            "note": "Legacy upstream crawler is disabled in Pixiv NAI Gallery.",
        }
    phase = _crawler_phase()
    if use_supervisor and SUPERVISOR_SCRIPT.exists():
        pid = _spawn_detached_ps(
            file_path=r"powershell.exe",
            arg_list=[
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SUPERVISOR_SCRIPT),
            ],
            title="aitag-crawler-supervisor",
        )
        return {
            "mode": "supervisor",
            "pid": pid,
            "phase": phase,
            "already_running": False,
        }

    pid = _spawn_detached_ps(
        file_path=sys.executable,
        arg_list=["-u", str(CRAWLER_SCRIPT), "--phase", phase],
        title="aitag-crawler",
    )
    return {
        "mode": "direct",
        "pid": pid,
        "phase": phase,
        "already_running": False,
    }


def start_crawler(*, use_supervisor: bool = True) -> dict[str, object]:
    """Compatibility alias: the product's crawler is Pixiv direct NAI intake."""
    _ = use_supervisor
    return start_pixiv_crawler(watch=True)


def start_qq_crawler(*, watch: bool = True) -> dict[str, object]:
    invalidate_process_cache()
    existing = _list_qq_crawler_pids_uncached()
    if existing:
        return {
            "mode": "existing",
            "pid": existing[0],
            "pids": existing,
            "watch": bool(watch),
            "already_running": True,
        }
    pid = _spawn_detached_ps(
        file_path=sys.executable,
        arg_list=["-u", str(QQ_CRAWLER_SCRIPT), "--watch" if watch else "--once"],
        title="aitag-crawler-qq",
    )
    return {
        "mode": "watch" if watch else "once",
        "pid": pid,
        "watch": bool(watch),
        "already_running": False,
    }


def start_pixiv_crawler(*, watch: bool = True) -> dict[str, object]:
    invalidate_process_cache()
    from gallery_snapshot import maintenance_mode_active

    if maintenance_mode_active(data_dir()):
        return {
            "mode": "maintenance",
            "watch": bool(watch),
            "already_running": False,
            "started": False,
            "note": "Gallery maintenance (snapshot restore) is in progress; "
            "crawler start is blocked.",
        }
    existing = _list_pixiv_crawler_pids_uncached()
    if existing:
        return {
            "mode": "existing",
            "pid": existing[0],
            "pids": existing,
            "watch": bool(watch),
            "already_running": True,
        }
    # Cross-process guard: a CLI-started crawler holds the lock file without
    # necessarily matching the process scan (e.g. different interpreter name).
    lock = CrawlerFileLock(pixiv_crawler_lock_path())
    holder = lock.holder_pid()
    if holder and pid_alive(holder):
        return {
            "mode": "existing",
            "pid": holder,
            "pids": [holder],
            "watch": bool(watch),
            "already_running": True,
        }
    from gallery_guard import require_gallery_for_crawler

    require_gallery_for_crawler()
    pid = _spawn_detached_ps(
        file_path=sys.executable,
        arg_list=[
            "-u",
            str(PIXIV_CRAWLER_SCRIPT),
            "--watch" if watch else "--once",
        ],
        title="pixiv-nai-crawler",
    )
    return {
        "mode": "watch" if watch else "once",
        "pid": pid,
        "watch": bool(watch),
        "already_running": False,
    }


def multi_crawler_status() -> dict[str, dict[str, object]]:
    site = list_crawler_pids()
    supervisors = list_supervisor_pids()
    qq = list_qq_crawler_pids()
    pixiv = list_pixiv_crawler_pids()
    return {
        "site": {
            "running": bool(site or supervisors),
            "crawler_pids": site,
            "supervisor_pids": supervisors,
            "disabled": True,
            "note": "Legacy upstream crawler is disabled; use Pixiv intake.",
        },
        "qqgroup": {
            "running": bool(qq),
            "crawler_pids": qq,
        },
        "pixiv": {
            "running": bool(pixiv),
            "crawler_pids": pixiv,
        },
        "codex": {
            "running": False,
            "crawler_pids": [],
            "note": "import-only gallery",
        },
    }


def start_crawler_target(
    target: str,
    *,
    phase: str | None = None,
    watch: bool = True,
) -> dict[str, object]:
    key = str(target or "pixiv").strip().lower()
    key = {"qq": "qqgroup", "website": "site", "aitag": "site"}.get(key, key)
    if phase:
        phase_key = str(phase).strip().lower()
        if phase_key not in {"all", "search", "detail", "preview"}:
            raise ValueError("invalid crawler phase")
    if key == "site":
        raise ValueError("legacy site crawler is disabled; use target=pixiv")
    if key == "qqgroup":
        return {"qqgroup": start_qq_crawler(watch=watch)}
    if key == "pixiv":
        return {"pixiv": start_pixiv_crawler(watch=watch)}
    if key == "codex":
        return {
            "codex": {
                "started": False,
                "already_running": False,
                "note": "Codex gallery is import-only",
            }
        }
    if key == "all":
        return {"pixiv": start_pixiv_crawler(watch=watch)}
    raise ValueError(f"unsupported crawler target: {target}")


def stop_qq_crawler_processes() -> dict[str, list[int]]:
    invalidate_process_cache()
    stopped = {
        "crawler_qq": _kill_owned_processes(_list_qq_crawler_processes_uncached())
    }
    invalidate_process_cache()
    return stopped


def stop_pixiv_crawler_processes() -> dict[str, list[int]]:
    invalidate_process_cache()
    stopped = {
        "crawler_pixiv": _kill_owned_processes(
            _list_pixiv_crawler_processes_uncached()
        )
    }
    invalidate_process_cache()
    return stopped


def stop_crawler_target(target: str) -> dict[str, dict[str, list[int]]]:
    key = str(target or "pixiv").strip().lower()
    key = {"qq": "qqgroup", "website": "site", "aitag": "site"}.get(key, key)
    if key == "site":
        return {"site": stop_crawler_processes()}
    if key == "qqgroup":
        return {"qqgroup": stop_qq_crawler_processes()}
    if key == "pixiv":
        return {"pixiv": stop_pixiv_crawler_processes()}
    if key == "codex":
        return {"codex": {}}
    if key == "all":
        return {
            "pixiv": stop_crawler_processes(),
            "qqgroup": stop_qq_crawler_processes(),
            "codex": {},
        }
    raise ValueError(f"unsupported crawler target: {target}")


def _wait_for_crawler(*, attempts: int = 20, interval: float = 0.5) -> bool:
    for _ in range(attempts):
        if crawler_running():
            return True
        time.sleep(interval)
    return False


def restart_crawler(*, wait_sec: float = 2.0) -> dict[str, object]:
    stopped = stop_crawler_processes()
    if wait_sec > 0:
        time.sleep(wait_sec)
    try:
        started = start_crawler(use_supervisor=True)
        alive = _wait_for_crawler()
        if not alive:
            # 监督脚本偶发未拉起子进程时，直接再起一份爬虫
            started = start_crawler(use_supervisor=False)
            alive = _wait_for_crawler(attempts=12)
    except ValueError as exc:
        return {
            "ok": False,
            "stopped": stopped,
            "started": {"started": False, "error": str(exc)},
            "crawler_running": False,
            "message": str(exc),
        }
    return {
        "ok": alive,
        "stopped": stopped,
        "started": started,
        "crawler_running": alive,
        "message": "爬虫已重启" if alive else "已发送重启命令，请稍候刷新状态",
    }
