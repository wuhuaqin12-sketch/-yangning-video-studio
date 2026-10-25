@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "ALIGNMENT_PY=program\.venv\Scripts\python.exe"
if exist "%LocalAppData%\YangNingStudioDesktop\runtime\Scripts\python.exe" set "ALIGNMENT_PY=%LocalAppData%\YangNingStudioDesktop\runtime\Scripts\python.exe"
if not exist "%ALIGNMENT_PY%" (
  echo Please run START.bat once first, then close the app.
  pause
  exit /b 1
)
echo Close YangNing VideoStudio before continuing. Internet required.
pause
"%ALIGNMENT_PY%" program\alignment_runtime.py --repair > alignment_repair.log 2>&1
if errorlevel 1 (
  echo Repair failed. Please send alignment_repair.log.
) else (
  echo Repair completed. Open START.bat.
)
pause
