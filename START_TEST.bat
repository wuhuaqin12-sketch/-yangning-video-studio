@echo off
setlocal
chcp 65001 >nul
set "YANGNING_PREVIEW_ROOT=%LOCALAPPDATA%\YangNingStudioDesktopPreview"
if not exist "%YANGNING_PREVIEW_ROOT%\runtime\Scripts\pythonw.exe" (
  echo 请先运行 INSTALL_TEST.bat。
  pause
  exit /b 1
)
start "" "%YANGNING_PREVIEW_ROOT%\runtime\Scripts\pythonw.exe" "%YANGNING_PREVIEW_ROOT%\desktop_launch.py"
