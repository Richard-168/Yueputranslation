@echo off
setlocal
set "YUEPU_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%YUEPU_PYTHON%" set "YUEPU_PYTHON=%~dp0experiments\offline-poc\.venv\Scripts\pythonw.exe"
if not exist "%YUEPU_PYTHON%" (
  echo Python environment is missing. Run Initialize-YuePu.cmd first.
  pause
  exit /b 1
)
start "" "%YUEPU_PYTHON%" -B "%~dp0experiments\offline-poc\desktop_qt.py"
