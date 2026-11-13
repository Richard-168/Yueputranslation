@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Python environment is missing. Prepare the offline verification environment first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -c "import PySide6.QtWidgets" >nul 2>&1
if errorlevel 1 (
  echo Qt interface dependency is missing. Please restore the project environment.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" -B "%~dp0desktop_qt.py"
exit /b 0
