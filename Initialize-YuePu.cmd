@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1

set "YUEPU_SETUP_RESULT=1"
set "YUEPU_SETUP_INTERACTIVE="
set "YUEPU_SETUP_PLAN="
set "YUEPU_SETUP_PROFILE=pro"
if /I "%~1"=="--help" goto help
if /I "%~1"=="--plan" (
    set "YUEPU_SETUP_PLAN=1"
    shift
    goto named_profile
)
if not "%~1"=="" goto named_profile
set "YUEPU_SETUP_INTERACTIVE=1"
echo Choose the Windows models to prepare:
echo   [P] Pro: text, speech and paragraph review ^(default^)
echo   [F] Flash: text, speech recognition and both voices
echo   [T] Text: Cantonese / Mandarin text translation only
choice /C PFT /N /T 15 /D P /M "Choose P, F or T. Pro starts in 15 seconds: "
if errorlevel 4 goto usage_error
if not errorlevel 1 goto finish
if errorlevel 3 (
    set "YUEPU_SETUP_PROFILE=text"
) else if errorlevel 2 (
    set "YUEPU_SETUP_PROFILE=flash"
)
goto profile_selected

:named_profile
if not "%~2"=="" goto usage_error
if "%~1"=="" goto profile_selected
if /I "%~1"=="pro" goto profile_selected
if /I "%~1"=="text" (
    set "YUEPU_SETUP_PROFILE=text"
    goto profile_selected
)
if /I "%~1"=="flash" (
    set "YUEPU_SETUP_PROFILE=flash"
    goto profile_selected
)
goto usage_error

:profile_selected
set "YUEPU_SETUP_BASE=asr canto hymt2 runtime mandarin vad"
if "%YUEPU_SETUP_PROFILE%"=="text" set "YUEPU_SETUP_BASE=hymt2 runtime"
echo Selected model profile: %YUEPU_SETUP_PROFILE%
if defined YUEPU_SETUP_PLAN goto prepare
set "YUEPU_SETUP_PYTHON=.venv\Scripts\python.exe"
set "YUEPU_SETUP_CHECK=import sys, sysconfig; sys.exit(not (sys.version_info[:2] == (3, 12) and sysconfig.get_platform() == 'win-amd64'))"

set "YUEPU_SETUP_STAGE=Python environment setup"
echo [1/3] Preparing the project Python environment...
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
echo [2/3] Installing Python dependencies...
"%YUEPU_SETUP_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    "%YUEPU_SETUP_PYTHON%" -m ensurepip --upgrade || goto failed
)
"%YUEPU_SETUP_PYTHON%" -m pip --disable-pip-version-check install -e ".[offline,dev]" || goto failed

:prepare
set "YUEPU_SETUP_STAGE=model and runtime preparation"
if not defined YUEPU_SETUP_PLAN echo [3/3] Preparing the selected models and the offline runtime...
call :prepare_components %YUEPU_SETUP_BASE% || goto failed
if "%YUEPU_SETUP_PROFILE%"=="pro" (
    call :prepare_components song-asr-large || goto failed
)
if "%YUEPU_SETUP_PROFILE%"=="text" echo With text-only assets, new preferences start with automatic speech off. Existing preferences take priority.
if "%YUEPU_SETUP_PROFILE%"=="flash" echo With Flash assets, new preferences select Flash. If you saved Pro earlier, select Flash in the audio options.
if not defined YUEPU_SETUP_PLAN echo Setup complete. Open Start-YuePu.cmd to start the app.
set "YUEPU_SETUP_RESULT=0"
goto finish

:prepare_components
echo Model components: %*
if defined YUEPU_SETUP_PLAN exit /b 0
"%YUEPU_SETUP_PYTHON%" experiments\offline-poc\prepare_models.py %*
exit /b %errorlevel%

:usage_error
echo Invalid model profile or arguments.
set "YUEPU_SETUP_RESULT=2"
goto usage

:help
set "YUEPU_SETUP_RESULT=0"
:usage
echo Usage: Initialize-YuePu.cmd [--plan] [text^|flash^|pro]
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
if defined YUEPU_SETUP_INTERACTIVE pause
exit /b %YUEPU_SETUP_RESULT%
