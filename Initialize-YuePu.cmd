@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1

set "YUEPU_SETUP_RESULT=1"
set "YUEPU_SETUP_PYTHON=.venv\Scripts\python.exe"
set "YUEPU_SETUP_CHECK=import sys, sysconfig; sys.exit(not (sys.version_info[:2] == (3, 12) and sysconfig.get_platform() == 'win-amd64'))"

set "YUEPU_SETUP_STAGE=Python environment setup"
echo [1/4] Preparing the project Python environment...
if exist "%YUEPU_SETUP_PYTHON%" goto check_environment

py -3.12 -c "%YUEPU_SETUP_CHECK%" >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv --without-pip .venv || goto failed
) else (
    python -c "%YUEPU_SETUP_CHECK%" >nul 2>&1 || goto missing_python
    python -m venv --without-pip .venv || goto failed
)

:check_environment
"%YUEPU_SETUP_PYTHON%" -c "%YUEPU_SETUP_CHECK%" >nul 2>&1 || goto invalid_environment
if not exist ".venv\Scripts\pythonw.exe" goto invalid_environment

set "YUEPU_SETUP_STAGE=Python dependency installation"
echo [2/4] Installing Python dependencies...
"%YUEPU_SETUP_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    "%YUEPU_SETUP_PYTHON%" -m ensurepip --upgrade || goto failed
)
"%YUEPU_SETUP_PYTHON%" -m pip --disable-pip-version-check install -e ".[offline,dev]" || goto failed

set "YUEPU_SETUP_STAGE=base model and runtime preparation"
echo [3/4] Preparing base models and the offline runtime...
"%YUEPU_SETUP_PYTHON%" experiments\offline-poc\prepare_models.py asr canto hymt2 runtime mandarin vad || goto failed

set "YUEPU_SETUP_STAGE=pro model preparation"
echo [4/4] Preparing the pro model...
"%YUEPU_SETUP_PYTHON%" experiments\offline-poc\prepare_models.py song-asr-large || goto failed

echo Setup complete. Open Start-YuePu.cmd to start the app.
set "YUEPU_SETUP_RESULT=0"
goto finish

:missing_python
echo Install Python 3.12 for Windows x64 and run this script again.
goto failed

:invalid_environment
echo The .venv folder does not contain a working Windows x64 Python 3.12 environment.
echo Move .venv out of this folder and run this script again.

:failed
echo Setup stopped during %YUEPU_SETUP_STAGE%. Fix the error above and run this script again.

:finish
popd
pause
exit /b %YUEPU_SETUP_RESULT%
