@echo off
setlocal
cd /d "%~dp0"
call INSTALL.bat %*
exit /b %ERRORLEVEL%
