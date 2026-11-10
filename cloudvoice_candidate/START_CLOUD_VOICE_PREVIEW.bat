@echo off
setlocal
if not exist "%~dp0program\cloud_voice_preview.py" (
  echo Please extract the entire ZIP to a normal folder first.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_cloud_voice_preview.ps1"
if errorlevel 1 (
  echo Setup or launch did not finish. Keep the error text for diagnosis.
  pause
  exit /b 1
)
endlocal
