@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 program\restore_entry.py
  goto finished
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" program\restore_entry.py
  goto finished
)
python program\restore_entry.py
:finished
if errorlevel 1 (
  echo 恢复未完成，请保留上方错误信息。
) else (
  echo 已恢复到独立v12.11。关闭测试版后，从“杨宁视频工作室 测试版”快捷方式启动。
)
pause
