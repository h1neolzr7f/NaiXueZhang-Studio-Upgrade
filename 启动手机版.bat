@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

rem Desktop preview of /m only. The Android APK is standalone and does not use this.
set "GALLERY_HOST=0.0.0.0"
set "GALLERY_ALLOW_REMOTE=1"
set "GALLERY_OPEN_PATH=/m"
echo Opening the desktop /m preview. The phone APK does not need this PC server.
call "%~dp0START_GALLERY.bat" restart
exit /b %errorlevel%
