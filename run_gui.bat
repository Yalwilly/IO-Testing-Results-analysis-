@echo off
REM ============================================================
REM  IO Testing Results Analysis — Quick Launcher
REM  No installation needed. Just double-click this file.
REM ============================================================

cd /d "%~dp0"

REM Try py launcher first (Windows Python Launcher)
where py >NUL 2>&1
if not errorlevel 1 (
    py gui_launcher.py
    exit /b
)

REM Fallback to python
where python >NUL 2>&1
if not errorlevel 1 (
    python gui_launcher.py
    exit /b
)

REM Fallback to python3
where python3 >NUL 2>&1
if not errorlevel 1 (
    python3 gui_launcher.py
    exit /b
)

echo.
echo ERROR: Python not found on PATH.
echo Please install Python 3.9+ from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during installation.
pause
