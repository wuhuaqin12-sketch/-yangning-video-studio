@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist "program\.venv\Scripts\python.exe" (
  "program\.venv\Scripts\python.exe" program\install_desktop.py
  goto finished
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" program\install_desktop.py
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.12 3.13 3.11 3.10) do (
    py -%%V -c "import struct; assert struct.calcsize('P')==8" >nul 2>nul
    if not errorlevel 1 (
      py -%%V program\install_desktop.py
      goto finished
    )
  )
)
python -c "import sys,struct; assert (3,10)<=sys.version_info[:2]<=(3,13) and struct.calcsize('P')==8" >nul 2>nul
if not errorlevel 1 (
  python program\install_desktop.py
  goto finished
)
where winget >nul 2>nul
if errorlevel 1 (
  echo Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/
  echo Enable Python launcher and tkinter, then open START.bat again.
  pause
  exit /b 1
)
echo Installing the supported 64-bit Python runtime...
winget install --exact --id Python.Python.3.12 --architecture x64 --scope user --source winget
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" program\install_desktop.py
) else (
  echo Close this window and open START.bat again to refresh PATH.
  pause
)
:finished
if errorlevel 1 pause
endlocal
