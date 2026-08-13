from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil


EXIT_CONFIGURATION_ERROR = 2
EXIT_FOREIGN_LISTENER = 3
EXIT_STOP_FAILED = 4
_PYTHON_EXE = re.compile(r"^(?:pythonw?|pypy)(?:\d+(?:\.\d+)*)?\.exe$", re.IGNORECASE)


@dataclass(frozen=True)
class Listener:
    pid: int
    create_time: float
    command_line: tuple[str, ...]


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _canonical(path: Path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _script_argument(command_line: list[str]) -> str | None:
    """Return the script Python executes, rejecting -c/-m interpreter modes."""
    if len(command_line) < 2:
        return None
    if not _PYTHON_EXE.match(Path(command_line[0]).name):
        return None

    index = 1
    while index < len(command_line):
        argument = command_line[index]
        if argument == "--":
            index += 1
            break
        if not argument.startswith("-") or argument == "-":
            break
        lowered = argument.casefold()
        if lowered in {"-c", "-m"}:
            return None
        if lowered in {"-w", "-x"}:
            index += 2
        else:
            index += 1
    if index >= len(command_line):
        return None
    return command_line[index]


def _is_project_server(process: psutil.Process, server_script: Path) -> bool:
    command_line = process.cmdline()
    script_argument = _script_argument(command_line)
    if script_argument is None:
        return False

    candidate = Path(script_argument)
    if not candidate.is_absolute():
        candidate = Path(process.cwd()) / candidate
    return _canonical(candidate) == _canonical(server_script)


def _list_listeners(port: int) -> tuple[list[int], bool]:
    pids: set[int] = set()
    has_unidentified_listener = False
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, OSError) as exc:
        raise RuntimeError(f"Unable to inspect TCP listeners: {exc}") from exc

    for connection in connections:
        if (
            connection.status == psutil.CONN_LISTEN
            and connection.laddr
            and connection.laddr.port == port
        ):
            if connection.pid is None:
                has_unidentified_listener = True
            else:
                pids.add(int(connection.pid))
    return sorted(pids), has_unidentified_listener


def _inspect_listener(pid: int, server_script: Path, port: int) -> Listener | None:
    try:
        process = psutil.Process(pid)
        create_time = process.create_time()
        command_line = tuple(process.cmdline())
        if not _is_project_server(process, server_script):
            display_command = " ".join(command_line) or "<unavailable>"
            print(
                f"Refusing to stop non-gallery process PID {pid} on port {port}. "
                f"CommandLine: {display_command}",
                file=sys.stderr,
            )
            return None
        return Listener(pid=pid, create_time=create_time, command_line=command_line)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
        print(
            f"Refusing to stop unverified listener PID {pid} on port {port}: {exc}",
            file=sys.stderr,
        )
        return None


def _still_same_listener(listener: Listener, port: int) -> bool:
    try:
        process = psutil.Process(listener.pid)
        if process.create_time() != listener.create_time:
            return False
        listener_pids, has_unidentified = _list_listeners(port)
        return not has_unidentified and listener.pid in listener_pids
    except (psutil.NoSuchProcess, psutil.AccessDenied, RuntimeError, OSError):
        return False


def _stop_listener(listener: Listener, port: int) -> bool:
    if not _still_same_listener(listener, port):
        print(
            f"Refusing to stop PID {listener.pid}: listener identity changed before termination.",
            file=sys.stderr,
        )
        return False

    process = psutil.Process(listener.pid)
    print(f"Stopping gallery PID {listener.pid} on port {port}...")
    try:
        process.terminate()
        process.wait(timeout=5)
    except psutil.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    except psutil.NoSuchProcess:
        return True
    except (psutil.AccessDenied, OSError) as exc:
        print(f"Failed to stop gallery PID {listener.pid}: {exc}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Gallery process guard")
    parser.add_argument("--project-root", required=True, help="Project root directory")
    parser.add_argument("--port", type=_port, default=8797, help="Gallery port")
    parser.add_argument(
        "--action",
        type=str.casefold,
        choices=["check", "stop"],
        default="check",
        help="Action to perform",
    )
    args = parser.parse_args()

    project_root = Path(os.path.realpath(args.project_root))
    if not project_root.is_dir():
        print(f"Gallery project root does not exist: {project_root}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR
    server_script = project_root / "server.py"

    try:
        listener_pids, has_unidentified_listener = _list_listeners(args.port)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    if not listener_pids and not has_unidentified_listener:
        print(f"No listener is using port {args.port}.")
        return 0
    if has_unidentified_listener:
        print(
            f"Refusing to stop an unidentified listener on port {args.port}.",
            file=sys.stderr,
        )
        return EXIT_FOREIGN_LISTENER

    listeners: list[Listener] = []
    for pid in listener_pids:
        listener = _inspect_listener(pid, server_script, args.port)
        if listener is None:
            return EXIT_FOREIGN_LISTENER
        listeners.append(listener)

    if args.action == "check":
        pids = ", ".join(str(listener.pid) for listener in listeners)
        print(f"Port {args.port} is owned by this gallery project (PID {pids}).")
        return 0

    if not all(_stop_listener(listener, args.port) for listener in listeners):
        return EXIT_STOP_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main())
