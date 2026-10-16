@echo off
rem Builds a standalone Handpal.exe into dist\Handpal\ (no Python needed to run it).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv || exit /b 1
)
".venv\Scripts\python.exe" -m pip install -e ".[dev]" || exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed ^
    --name Handpal --icon assets\handpal.ico ^
    --add-data "handpal\fonts;handpal\fonts" ^
    --paths . handpal\__main__.py || exit /b 1

rem Drop Qt parts a widgets-only app never loads (Quick/QML, PDF, software OpenGL).
set QT=dist\Handpal\_internal\PySide6
del /q "%QT%\opengl32sw.dll" "%QT%\Qt6Quick*.dll" "%QT%\Qt6Qml*.dll" "%QT%\Qt6Pdf.dll" ^
    "%QT%\Qt6VirtualKeyboard*.dll" "%QT%\plugins\imageformats\qpdf.dll" 2>nul
rmdir /s /q "%QT%\translations" "%QT%\plugins\platforminputcontexts" 2>nul
echo.
echo Done: dist\Handpal\Handpal.exe
