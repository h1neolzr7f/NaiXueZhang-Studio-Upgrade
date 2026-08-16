@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

rem Keep Pixiv NAI Gallery isolated from aitag-mirror Gallery on 8787.
if not defined GALLERY_PORT set "GALLERY_PORT=8797"
set "PORTABLE_PYTHON=%~dp0runtime\python.exe"
set "PYTHON_SELECTOR=%~dp0scripts\select_python_runtime.bat"
if exist "%PYTHON_SELECTOR%" goto :use_shared_python_selector
if exist "%PORTABLE_PYTHON%" (
  set "GALLERY_PYTHON_EXE=%PORTABLE_PYTHON%"
  set "GALLERY_PYTHON_MODE=bundled portable runtime"
  goto :python_selector_ready
)
if exist "%~dp0.venv\Scripts\python.exe" (
  set "GALLERY_PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
  set "GALLERY_PYTHON_MODE=local environment"
  goto :python_selector_ready
)
for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined GALLERY_PYTHON_EXE set "GALLERY_PYTHON_EXE=%%P"
if defined GALLERY_PYTHON_EXE set "GALLERY_PYTHON_MODE=global Python"
goto :python_selector_ready

:use_shared_python_selector
call "%~dp0scripts\select_python_runtime.bat"

:python_selector_ready
rem Source installs still bootstrap an isolated .venv with the discovered global Python.
if /I "%GALLERY_PYTHON_MODE%"=="global Python" set "GALLERY_PYTHON_EXE="
set "PROCESS_GUARD=%~dp0scripts\gallery_process_guard.ps1"
set "LAUNCH_HELPER=%~dp0scripts\launch_server.vbs"
set "MODE=%~1"
if /I "%MODE%"=="" set "MODE=open"
if /I "%MODE%"=="open" goto :mode_valid
if /I "%MODE%"=="restart" goto :mode_valid
if /I "%MODE%"=="watch" goto :mode_valid
echo [ERROR] Mode must be open, restart, or watch.
if not defined GALLERY_NONINTERACTIVE pause
endlocal
exit /b 2

:mode_valid

if defined GALLERY_PYTHON_EXE goto :python_ready
if not exist "%~dp0INSTALL.bat" goto :installer_missing
echo First run detected. Preparing the local environment automatically...
set "GALLERY_BOOTSTRAP=1"
call "%~dp0INSTALL.bat"
set "BOOTSTRAP_RESULT=%errorlevel%"
set "GALLERY_BOOTSTRAP="
if not "%BOOTSTRAP_RESULT%"=="0" goto :bootstrap_failed
if exist "%PYTHON_SELECTOR%" (
  call "%~dp0scripts\select_python_runtime.bat"
) else if exist "%~dp0.venv\Scripts\python.exe" (
  set "GALLERY_PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
  set "GALLERY_PYTHON_MODE=local environment"
)

:python_ready
if not defined GALLERY_PYTHON_EXE goto :bootstrap_missing
goto :python_validated

:installer_missing
echo [ERROR] Both the bundled runtime and INSTALL.bat are missing.
if not defined GALLERY_NONINTERACTIVE pause
endlocal
exit /b 2

:bootstrap_failed
echo [ERROR] Automatic first-run setup failed with exit code %BOOTSTRAP_RESULT%.
echo Check the message above, then double-click this launcher to retry.
if not defined GALLERY_NONINTERACTIVE pause
endlocal & exit /b %BOOTSTRAP_RESULT%

:bootstrap_missing
echo [ERROR] Automatic setup finished but Python is still unavailable.
if not defined GALLERY_NONINTERACTIVE pause
endlocal
exit /b 2

:python_validated

if not exist "%PROCESS_GUARD%" (
  echo [ERROR] Startup safety helper is missing: "%PROCESS_GUARD%"
  if not defined GALLERY_NONINTERACTIVE pause
  endlocal
  exit /b 2
)

powershell.exe -NoProfile -NonInteractive -Command "$raw=$env:GALLERY_PORT; if ($raw -notmatch '^[0-9]+\z') { exit 1 }; $port=[int]$raw; if ($port -lt 1 -or $port -gt 65535) { exit 1 }; exit 0" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] GALLERY_PORT must be an integer between 1 and 65535.
  if not defined GALLERY_NONINTERACTIVE pause
  endlocal
  exit /b 2
)
set "GALLERY_URL=http://127.0.0.1:%GALLERY_PORT%"

if not exist "%LAUNCH_HELPER%" (
  echo [ERROR] Server launch helper is missing: "%LAUNCH_HELPER%"
  if not defined GALLERY_NONINTERACTIVE pause
  endlocal
  exit /b 2
)

if not exist "logs" mkdir "logs"

if /I "%MODE%"=="restart" goto :do_restart
if /I "%MODE%"=="watch" goto :do_watch

call :check_health
if not errorlevel 1 (
  call :guard_listener Check
  if errorlevel 1 (
    echo [ERROR] Port %GALLERY_PORT% answered the health check but is not owned by this project.
    if not defined GALLERY_NONINTERACTIVE pause
    endlocal
    exit /b 3
  )
  echo Nai学长工作室 is already running on port %GALLERY_PORT%.
  call :open_browser
  endlocal
  exit /b 0
)

echo No healthy Gallery instance detected. Checking port %GALLERY_PORT% safely...
call :guard_listener Stop
if errorlevel 1 (
  echo [ERROR] Port %GALLERY_PORT% belongs to another program. It was not stopped.
  if not defined GALLERY_NONINTERACTIVE pause
  endlocal
  exit /b 3
)
goto :start_server

:do_restart
echo Restarting Nai学长工作室 on port %GALLERY_PORT%...
call :guard_listener Stop
if errorlevel 1 (
  echo [ERROR] Restart cancelled because port %GALLERY_PORT% belongs to another program.
  if not defined GALLERY_NONINTERACTIVE pause
  endlocal
  exit /b 3
)
powershell.exe -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 1" >nul 2>&1
goto :start_server

:do_watch
echo Gallery watchdog is keeping %GALLERY_URL% alive. Close this window to stop watching.
:watch_loop
call :check_health
if errorlevel 1 (
  echo [%date% %time%] Health check failed. Attempting a safe restart...
  call "%~f0" restart
  if errorlevel 1 (
    echo [%date% %time%] Safe restart refused or failed. Watchdog is stopping.
    endlocal
    exit /b 3
  )
) else (
  call :guard_listener Check
  if errorlevel 1 (
    echo [%date% %time%] Port owner check failed. Watchdog is stopping without killing it.
    endlocal
    exit /b 3
  )
)
powershell.exe -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 30" >nul 2>&1
goto :watch_loop

:start_server
echo Starting Nai学长工作室 with %GALLERY_PYTHON_MODE%...
if not exist "%~dp0logs" mkdir "%~dp0logs"
set "GALLERY_LOG=%~dp0logs\server-%GALLERY_PORT%.log"
wscript.exe "%LAUNCH_HELPER%" "%GALLERY_PYTHON_EXE%" "%~dp0server.py" "%~dp0." "%GALLERY_LOG%"
if errorlevel 1 (
  echo [ERROR] The hidden server process could not be launched.
  if not defined GALLERY_NONINTERACTIVE pause
  endlocal
  exit /b 1
)

echo Waiting for the server to be ready...
set "READY=0"
for /L %%I in (1,1,60) do (
  call :check_health
  if not errorlevel 1 (
    set "READY=1"
    goto :server_ready
  )
  powershell.exe -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 1" >nul 2>&1
)

:server_ready
if "%READY%"=="1" (
  echo Server is up.
) else (
  echo [ERROR] Server health check timed out. See "%~dp0logs\server.log".
  if not defined GALLERY_NONINTERACTIVE pause
  endlocal
  exit /b 1
)

call :open_browser
echo Open: %GALLERY_URL%/
echo Log: %GALLERY_LOG%
if /I "%MODE%"=="restart" echo Restart complete. Hard-refresh the browser if the UI looks stale.
endlocal
exit /b 0

:check_health
"%GALLERY_PYTHON_EXE%" -c "import urllib.request; opener=urllib.request.build_opener(urllib.request.ProxyHandler({})); response=opener.open('%GALLERY_URL%/api/config', timeout=3); raise SystemExit(0 if response.status < 400 else 1)" >nul 2>nul
if "%errorlevel%"=="0" exit /b 0
exit /b 1

:guard_listener
set "ACT=%~1"
if "%ACT%"=="" set "ACT=Check"
powershell.exe -NoProfile -InputFormat None -ExecutionPolicy Bypass -File "%PROCESS_GUARD%" -ProjectRoot "%~dp0." -Port %GALLERY_PORT% -Action %ACT%
if "%errorlevel%"=="0" exit /b 0
exit /b 1

:open_browser
if /I "%GALLERY_NO_BROWSER%"=="1" exit /b 0
start "" "%GALLERY_URL%/" >nul 2>nul
if not errorlevel 1 exit /b 0
powershell.exe -NoProfile -NonInteractive -Command "try { Start-Process $env:GALLERY_URL; exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 exit /b 0
echo [WARN] Could not open the default browser. Open %GALLERY_URL%/ manually.
exit /b 1
