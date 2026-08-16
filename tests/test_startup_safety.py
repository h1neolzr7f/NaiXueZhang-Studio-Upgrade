from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import venv
from unittest import mock
from pathlib import Path

from scripts import gallery_process_guard as python_process_guard


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESS_GUARD = PROJECT_ROOT / "scripts" / "gallery_process_guard.ps1"
PYTHON_PROCESS_GUARD = PROJECT_ROOT / "scripts" / "gallery_process_guard.py"
LAUNCH_HELPER = PROJECT_ROOT / "scripts" / "launch_server.vbs"
SHORTCUT_HELPER = PROJECT_ROOT / "scripts" / "create_desktop_shortcuts.ps1"
START_SCRIPT = PROJECT_ROOT / "START_GALLERY.bat"
START_POWERSHELL = PROJECT_ROOT / "start_gallery.ps1"
INSTALL_SCRIPT = PROJECT_ROOT / "INSTALL.bat"


def _install_fixture_python(fixture: Path, *, with_pip: bool = False) -> Path:
    fixture_venv = fixture / ".venv"
    venv.EnvBuilder(with_pip=with_pip, clear=True).create(fixture_venv)
    return fixture_venv / "Scripts" / "python.exe"


@unittest.skipUnless(os.name == "nt", "cmd.exe/powershell one-click contract is Windows-only")
class StartupScriptContractTests(unittest.TestCase):
    def test_start_does_not_install_or_create_dependencies(self) -> None:
        source = START_SCRIPT.read_text(encoding="utf-8").lower()

        self.assertNotIn("pip install", source)
        self.assertNotIn("python -m venv", source)

    def test_missing_runtime_and_installer_exits_with_clear_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            shutil.copy2(START_SCRIPT, fixture / START_SCRIPT.name)
            env = os.environ.copy()
            env["GALLERY_NONINTERACTIVE"] = "1"
            env["GALLERY_NO_BROWSER"] = "1"

            result = subprocess.run(
                ["cmd.exe", "/d", "/c", str(fixture / START_SCRIPT.name)],
                cwd=fixture,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            output = result.stdout + result.stderr

            self.assertEqual(2, result.returncode, output)
            self.assertIn("INSTALL.bat", output)
            self.assertIn("bundled runtime", output)

    def test_missing_runtime_uses_non_recursive_first_run_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            shutil.copy2(START_SCRIPT, fixture / START_SCRIPT.name)
            (fixture / INSTALL_SCRIPT.name).write_text(
                "@echo off\r\n"
                "> bootstrap-mode.txt echo %GALLERY_BOOTSTRAP%\r\n"
                "exit /b 9\r\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["GALLERY_NONINTERACTIVE"] = "1"
            env["GALLERY_NO_BROWSER"] = "1"

            result = subprocess.run(
                ["cmd.exe", "/d", "/c", str(fixture / START_SCRIPT.name)],
                cwd=fixture,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            output = result.stdout + result.stderr
            bootstrap_mode = (fixture / "bootstrap-mode.txt").read_text(
                encoding="utf-8"
            ).strip()

        self.assertEqual(9, result.returncode, output)
        self.assertEqual("1", bootstrap_mode)
        self.assertIn("Automatic first-run setup failed", output)

    def test_existing_venv_starts_without_global_python_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "gallery project"
            fixture.mkdir()
            shutil.copy2(START_SCRIPT, fixture / START_SCRIPT.name)
            (fixture / "scripts").mkdir()
            shutil.copy2(PROCESS_GUARD, fixture / "scripts" / PROCESS_GUARD.name)
            shutil.copy2(LAUNCH_HELPER, fixture / "scripts" / LAUNCH_HELPER.name)
            _install_fixture_python(fixture)
            (fixture / "server.py").write_text(
                "import os\n"
                "print('fixture server booted', flush=True)\n"
                "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
                "class Handler(BaseHTTPRequestHandler):\n"
                "    def do_GET(self):\n"
                "        if self.path == '/api/config':\n"
                "            self.send_response(200)\n"
                "            self.end_headers()\n"
                "            self.wfile.write(b'{}')\n"
                "        else:\n"
                "            self.send_response(404)\n"
                "            self.end_headers()\n"
                "    def log_message(self, *args):\n"
                "        pass\n"
                "HTTPServer(('127.0.0.1', int(os.environ['GALLERY_PORT'])), Handler).serve_forever()\n",
                encoding="utf-8",
            )
            port = _free_port()
            env = os.environ.copy()
            env["GALLERY_PORT"] = str(port)
            env["GALLERY_NONINTERACTIVE"] = "1"
            env["GALLERY_NO_BROWSER"] = "1"
            env["PATH"] = ";".join(
                [
                    os.environ["SystemRoot"] + r"\System32",
                    os.environ["SystemRoot"],
                    os.environ["SystemRoot"] + r"\System32\WindowsPowerShell\v1.0",
                ]
            )

            try:
                python_lookup = subprocess.run(
                    ["where.exe", "python"],
                    env=env,
                    capture_output=True,
                    timeout=5,
                )
                self.assertNotEqual(0, python_lookup.returncode)

                startup_output = fixture / "startup-output.txt"
                with startup_output.open("wb") as output_stream:
                    result = subprocess.run(
                        ["cmd.exe", "/d", "/c", str(fixture / START_SCRIPT.name)],
                        cwd=fixture,
                        env=env,
                        stdout=output_stream,
                        stderr=subprocess.STDOUT,
                        timeout=30,
                    )
                output = startup_output.read_text(encoding="utf-8", errors="replace")

                self.assertEqual(0, result.returncode, output)
                self.assertIn("Server is up", output)
                server_log = (fixture / "logs" / f"server-{port}.log").read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                self.assertIn("fixture server booted", server_log)
            finally:
                subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(fixture / "scripts" / PROCESS_GUARD.name),
                        "-ProjectRoot",
                        str(fixture),
                        "-Port",
                        str(port),
                        "-Action",
                        "Stop",
                    ],
                    capture_output=True,
                    timeout=15,
                )

    def test_invalid_port_is_rejected_before_health_or_process_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "gallery project"
            (fixture / "scripts").mkdir(parents=True)
            shutil.copy2(START_SCRIPT, fixture / START_SCRIPT.name)
            shutil.copy2(PROCESS_GUARD, fixture / "scripts" / PROCESS_GUARD.name)
            shutil.copy2(LAUNCH_HELPER, fixture / "scripts" / LAUNCH_HELPER.name)
            _install_fixture_python(fixture)
            env = os.environ.copy()
            env["GALLERY_PORT"] = "not-a-port"
            env["GALLERY_NONINTERACTIVE"] = "1"
            env["GALLERY_NO_BROWSER"] = "1"

            result = subprocess.run(
                ["cmd.exe", "/d", "/c", str(fixture / START_SCRIPT.name)],
                cwd=fixture,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            output = result.stdout + result.stderr

        self.assertEqual(2, result.returncode, output)
        self.assertIn("GALLERY_PORT must be an integer between 1 and 65535", output)
        self.assertNotIn("belongs to another program", output)

    def test_unknown_mode_is_rejected_before_environment_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir)
            shutil.copy2(START_SCRIPT, fixture / START_SCRIPT.name)
            env = os.environ.copy()
            env["GALLERY_NONINTERACTIVE"] = "1"

            result = subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    str(fixture / START_SCRIPT.name),
                    "unsafe-mode",
                ],
                cwd=fixture,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            output = result.stdout + result.stderr

        self.assertEqual(2, result.returncode, output)
        self.assertIn("Mode must be open, restart, or watch", output)
        self.assertNotIn("local Python environment is missing", output)

    def test_powershell_entrypoint_handles_spaces_and_propagates_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "gallery project"
            fixture.mkdir()
            shutil.copy2(START_POWERSHELL, fixture / START_POWERSHELL.name)
            (fixture / START_SCRIPT.name).write_text(
                "@echo off\r\n"
                "> delegated-mode.txt echo %~1\r\n"
                "exit /b 7\r\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(fixture / START_POWERSHELL.name),
                    "-Mode",
                    "restart",
                ],
                cwd=fixture,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )

            delegated_mode = (fixture / "delegated-mode.txt").read_text(
                encoding="utf-8",
            ).strip()

        self.assertEqual(7, result.returncode, result.stdout + result.stderr)
        self.assertEqual("restart", delegated_mode)


@unittest.skipUnless(os.name == "nt", "INSTALL.bat contract is Windows-only")
class InstallScriptContractTests(unittest.TestCase):
    def test_install_prefers_lock_file_with_requirements_fallback(self) -> None:
        source = INSTALL_SCRIPT.read_text(encoding="utf-8").lower()

        fallback = 'set "requirements_file=requirements.txt"'
        prefer_lock = (
            'if exist "requirements.lock.txt" '
            'set "requirements_file=requirements.lock.txt"'
        )
        install_selected = 'pip install -r "%requirements_file%"'
        self.assertIn(fallback, source)
        self.assertIn(prefer_lock, source)
        self.assertIn(install_selected, source)
        self.assertLess(source.index(fallback), source.index(prefer_lock))
        self.assertLess(source.index(prefer_lock), source.index(install_selected))

    def test_noninteractive_install_never_pauses_or_auto_launches(self) -> None:
        source = INSTALL_SCRIPT.read_text(encoding="utf-8").lower()
        bare_pause_lines = [
            line
            for line in source.splitlines()
            if line.strip() == "pause"
        ]

        self.assertEqual([], bare_pause_lines)
        self.assertIn("if not defined gallery_noninteractive", source)
        self.assertIn("gallery_skip_launch", source)

    def test_shortcut_creation_reads_install_root_from_environment(self) -> None:
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        helper = SHORTCUT_HELPER.read_text(encoding="utf-8")

        self.assertIn("GALLERY_INSTALL_ROOT", source)
        self.assertIn("$env:GALLERY_INSTALL_ROOT", helper)
        self.assertIn("create_desktop_shortcuts.ps1", source)
        self.assertNotIn("$SC.TargetPath='%~dp0", source)

    def test_noninteractive_install_completes_in_path_with_space_and_apostrophe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "installer's project"
            fixture.mkdir()
            shutil.copy2(INSTALL_SCRIPT, fixture / INSTALL_SCRIPT.name)
            (fixture / "requirements.txt").write_text("", encoding="utf-8")
            _install_fixture_python(fixture, with_pip=True)
            env = os.environ.copy()
            env["GALLERY_NONINTERACTIVE"] = "1"
            env["GALLERY_SKIP_LAUNCH"] = "1"

            result = subprocess.run(
                ["cmd.exe", "/d", "/c", str(fixture / INSTALL_SCRIPT.name)],
                cwd=fixture,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertIn("non-interactive install", output.lower())


class PythonProcessGuardUnitTests(unittest.TestCase):
    def test_stop_uses_only_listener_ids_returned_for_requested_port(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            listener = python_process_guard.Listener(
                pid=4321,
                create_time=123.0,
                command_line=("python.exe", str(project_root / "server.py")),
            )
            argv = [
                "gallery_process_guard.py",
                "--project-root",
                str(project_root),
                "--port",
                "54321",
                "--action",
                "Stop",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    python_process_guard,
                    "_list_listeners",
                    return_value=([listener.pid], False),
                ) as list_listeners,
                mock.patch.object(
                    python_process_guard,
                    "_inspect_listener",
                    return_value=listener,
                ) as inspect_listener,
                mock.patch.object(
                    python_process_guard,
                    "_stop_listener",
                    return_value=True,
                ) as stop_listener,
            ):
                result = python_process_guard.main()

        self.assertEqual(0, result)
        list_listeners.assert_called_once_with(54321)
        inspect_listener.assert_called_once()
        called_pid, called_script, called_port = inspect_listener.call_args.args
        self.assertEqual(called_pid, listener.pid)
        self.assertEqual(
            os.path.normcase(os.path.realpath(called_script)),
            os.path.normcase(os.path.realpath(project_root / "server.py")),
        )
        self.assertEqual(called_port, 54321)
        stop_listener.assert_called_once_with(listener, 54321)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@unittest.skipUnless(os.name == "nt", "gallery_process_guard.ps1 is Windows-only")
class StartupProcessSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._temp_dir.name)
        self.processes: list[subprocess.Popen[str]] = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self._temp_dir.cleanup()

    def _start_listener(
        self,
        script_dir: Path,
        port: int,
        script_name: str = "foreign_listener.py",
        extra_args: list[str] | None = None,
    ) -> subprocess.Popen[str]:
        script_dir.mkdir(parents=True, exist_ok=True)
        ready_file = script_dir / f"ready-{port}.txt"
        script = script_dir / script_name
        script.write_text(
            "import pathlib, socket, sys, time\n"
            "sock = socket.socket()\n"
            "sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            "sock.bind(('127.0.0.1', int(sys.argv[1])))\n"
            "sock.listen()\n"
            "pathlib.Path(sys.argv[2]).write_text('ready')\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [
                sys.executable,
                str(script),
                str(port),
                str(ready_file),
                *(extra_args or []),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.processes.append(process)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not ready_file.exists():
            if process.poll() is not None:
                self.fail("temporary listener exited before binding")
            time.sleep(0.05)
        self.assertTrue(ready_file.exists(), "temporary listener did not become ready")
        return process

    def _run_guard(
        self,
        project_root: Path,
        port: int,
        action: str = "Stop",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PROCESS_GUARD),
                "-ProjectRoot",
                str(project_root),
                "-Port",
                str(port),
                "-Action",
                action,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )

    def _run_python_guard(
        self,
        project_root: Path,
        port: int,
        action: str = "Check",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(PYTHON_PROCESS_GUARD),
                "--project-root",
                str(project_root),
                "--port",
                str(port),
                "--action",
                action,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )

    def test_no_listener_is_a_safe_noop(self) -> None:
        expected_project = self.temp_root / "gallery-project"
        expected_project.mkdir()
        port = _free_port()

        result = self._run_guard(expected_project, port)
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertIn(f"No listener is using port {port}", output)

    def test_missing_project_root_returns_configuration_exit_code(self) -> None:
        missing_project = self.temp_root / "missing-project"
        port = _free_port()

        result = self._run_guard(missing_project, port, "Check")
        output = result.stdout + result.stderr

        self.assertEqual(2, result.returncode, output)
        self.assertIn("project root does not exist", output)

    def test_refuses_to_stop_listener_from_another_project(self) -> None:
        expected_project = self.temp_root / "gallery-project"
        expected_project.mkdir()
        port = _free_port()
        listener = self._start_listener(self.temp_root / "foreign-project", port)

        result = self._run_guard(expected_project, port)
        output = result.stdout + result.stderr

        self.assertEqual(3, result.returncode, output)
        self.assertIn("Refusing to stop non-gallery process", output)
        self.assertIsNone(listener.poll(), output)

    def test_stops_server_py_listener_from_the_same_project(self) -> None:
        expected_project = self.temp_root / "gallery project"
        port = _free_port()
        listener = self._start_listener(expected_project, port, "server.py")

        result = self._run_guard(expected_project, port)
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        listener.wait(timeout=5)
        self.assertIsNotNone(listener.returncode, output)

    def test_stops_server_py_listener_started_with_relative_path(self) -> None:
        """Relative server.py invocation (wscript/other launchers) is still owned."""
        expected_project = self.temp_root / "gallery project"
        expected_project.mkdir(parents=True)
        port = _free_port()
        ready_file = expected_project / f"ready-{port}.txt"
        script = expected_project / "server.py"
        script.write_text(
"import pathlib, socket, sys, time\n"
            "sock = socket.socket()\n"
            "sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            "sock.bind(('127.0.0.1', int(sys.argv[1])))\n"
            "sock.listen()\n"
            "pathlib.Path(sys.argv[2]).write_text('ready')\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "server.py",  # relative path launch
                str(port),
                str(ready_file),
            ],
            cwd=expected_project,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.processes.append(process)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not ready_file.exists():
            if process.poll() is not None:
                self.fail("temporary listener exited before binding")
            time.sleep(0.05)
        self.assertTrue(ready_file.exists(), "temporary listener did not become ready")

        result = self._run_guard(expected_project, port)
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        process.wait(timeout=5)
        self.assertIsNotNone(process.returncode, output)
    def test_refuses_foreign_script_that_only_mentions_project_server_as_extra_argument(
        self,
    ) -> None:
        expected_project = self.temp_root / "gallery project"
        expected_project.mkdir()
        port = _free_port()
        listener = self._start_listener(
            self.temp_root / "foreign project",
            port,
            extra_args=[str(expected_project / "server.py")],
        )

        result = self._run_guard(expected_project, port)
        output = result.stdout + result.stderr

        self.assertEqual(3, result.returncode, output)
        self.assertIn("Refusing to stop non-gallery process", output)
        self.assertIsNone(listener.poll(), output)

    def test_check_accepts_same_project_without_stopping_it(self) -> None:
        expected_project = self.temp_root / "gallery-project"
        port = _free_port()
        listener = self._start_listener(expected_project, port, "server.py")

        result = self._run_guard(expected_project, port, "Check")
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertIn("owned by this gallery project", output)
        self.assertIsNone(listener.poll(), output)

    def test_python_guard_only_considers_the_requested_port(self) -> None:
        expected_project = self.temp_root / "gallery-project"
        owned_port = _free_port()
        owned_listener = self._start_listener(expected_project, owned_port, "server.py")
        unused_port = _free_port()

        result = self._run_python_guard(expected_project, unused_port, "Check")
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertIn(f"No listener is using port {unused_port}", output)
        self.assertIsNone(owned_listener.poll(), output)

    def test_python_guard_refuses_foreign_listener_even_with_owned_server_elsewhere(self) -> None:
        expected_project = self.temp_root / "gallery-project"
        owned_port = _free_port()
        owned_listener = self._start_listener(expected_project, owned_port, "server.py")
        foreign_port = _free_port()
        foreign_listener = self._start_listener(
            self.temp_root / "foreign-project",
            foreign_port,
        )

        result = self._run_python_guard(expected_project, foreign_port, "Check")
        output = result.stdout + result.stderr

        self.assertEqual(3, result.returncode, output)
        self.assertIn("Refusing to stop non-gallery process", output)
        self.assertIsNone(owned_listener.poll(), output)
        self.assertIsNone(foreign_listener.poll(), output)

    def test_python_guard_reports_only_same_project_listener_on_requested_port(self) -> None:
        expected_project = self.temp_root / "gallery-project"
        target_port = _free_port()
        target = self._start_listener(expected_project, target_port, "server.py")
        other_port = _free_port()
        other = self._start_listener(expected_project, other_port, "server.py")

        result = self._run_python_guard(expected_project, target_port, "Check")
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertIn(f"Port {target_port} is owned by this gallery project", output)
        self.assertIsNone(target.poll(), output)
        self.assertIsNone(other.poll(), output)

    def test_restart_refuses_foreign_listener_without_terminating_it(self) -> None:
        fixture = self.temp_root / "gallery-project"
        (fixture / ".venv" / "Scripts").mkdir(parents=True)
        (fixture / ".venv" / "Scripts" / "python.exe").touch()
        (fixture / "scripts").mkdir()
        shutil.copy2(START_SCRIPT, fixture / START_SCRIPT.name)
        shutil.copy2(PROCESS_GUARD, fixture / "scripts" / PROCESS_GUARD.name)
        shutil.copy2(LAUNCH_HELPER, fixture / "scripts" / LAUNCH_HELPER.name)
        port = _free_port()
        listener = self._start_listener(self.temp_root / "foreign-project", port)
        env = os.environ.copy()
        env["GALLERY_PORT"] = str(port)
        env["GALLERY_NONINTERACTIVE"] = "1"
        env["GALLERY_NO_BROWSER"] = "1"

        result = subprocess.run(
            ["cmd.exe", "/d", "/c", str(fixture / START_SCRIPT.name), "restart"],
            cwd=fixture,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        output = result.stdout + result.stderr

        self.assertEqual(3, result.returncode, output)
        self.assertIn("Restart cancelled", output)
        self.assertIn("Refusing to stop non-gallery process", output)
        self.assertIsNone(listener.poll(), output)


if __name__ == "__main__":
    unittest.main()
