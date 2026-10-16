@echo off
rem Starts Handpal without a console window. First run: creates the virtual env.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up Handpal for the first time...
    python -m venv .venv || exit /b 1
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m handpal
