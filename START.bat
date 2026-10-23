@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist "program\.venv\Scripts\python.exe" (
  "program\.venv\Scripts\python.exe" -I program\python_check.py >nul 2>nul
  if not errorlevel 1 (
    "program\.venv\Scripts\python.exe" program\bootstrap.py %*
    goto finished
  )
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" -I program\python_check.py >nul 2>nul
  if not errorlevel 1 (
    "%LocalAppData%\Programs\Python\Python312\python.exe" program\bootstrap.py %*
    goto finished
  )
)
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.12 3.11 3.10 3.13) do (
    py -%%V -I program\python_check.py >nul 2>nul
    if not errorlevel 1 (
      py -%%V program\bootstrap.py %*
      goto finished
    )
  )
)
python -I program\python_check.py >nul 2>nul
if not errorlevel 1 (
  python program\bootstrap.py %*
  goto finished
)
where winget >nul 2>nul
if errorlevel 1 (
  echo Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/
  echo Enable Python launcher and tkinter, then open START.bat again.
  if /I not "%~1"=="--quiet" pause
  exit /b 1
)
echo Preparing standard 64-bit Python 3.12; Microsoft Store Python is skipped...
winget install --exact --id Python.Python.3.12 --architecture x64 --scope user --source winget --accept-package-agreements --accept-source-agreements
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" -I program\python_check.py
  if not errorlevel 1 (
    "%LocalAppData%\Programs\Python\Python312\python.exe" program\bootstrap.py %*
    goto finished
  )
  echo Python validation failed. Please keep this error window.
  if /I not "%~1"=="--quiet" pause
  exit /b 1
) else (
  echo Close this window and open START.bat again to refresh PATH.
  if /I not "%~1"=="--quiet" pause
  exit /b 1
)
:finished
set "YANGNING_INSTALL_RESULT=%ERRORLEVEL%"
if not "%YANGNING_INSTALL_RESULT%"=="0" if /I not "%~1"=="--quiet" pause
exit /b %YANGNING_INSTALL_RESULT%
