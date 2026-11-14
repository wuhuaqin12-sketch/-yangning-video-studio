@echo off
setlocal
chcp 65001 >nul
set "YANGNING_PREVIEW_ROOT=%LOCALAPPDATA%\YangNingStudioDesktopPreview"
set "YANGNING_PREVIEW_PY=%YANGNING_PREVIEW_ROOT%\runtime\Scripts\python.exe"
if not exist "%YANGNING_PREVIEW_PY%" (
  echo 请先运行 INSTALL_TEST.bat 安装独立测试版。
  pause
  exit /b 1
)
"%YANGNING_PREVIEW_PY%" -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
"%YANGNING_PREVIEW_PY%" -m pip install demucs==4.1.0
if errorlevel 1 goto failed
echo 模型程序已安装。首次试听仍需下载模型权重。不会安装到v12.11运行环境。
pause
exit /b 0
:failed
echo 安装未完成，请保留此窗口的错误信息；未更改稳定版。
pause
exit /b 1
