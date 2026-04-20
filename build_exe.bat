@echo off
REM ============================================================
REM Build IO Testing Results Analysis GUI into a single .exe
REM ============================================================
REM
REM OFFLINE INSTALL (if pip cannot reach the internet):
REM   1. On a machine WITH internet, run:
REM        pip download pyinstaller -d .\pyinstaller_wheels
REM   2. Copy the pyinstaller_wheels\ folder here
REM   3. Re-run this script — it will install from the local folder
REM ============================================================

echo Checking PyInstaller...
python -m pyinstaller --version >NUL 2>&1
if not errorlevel 1 (
    echo PyInstaller already installed.
    goto :build
)

REM Try offline wheels folder first
if exist "%~dp0pyinstaller_wheels\" (
    echo Installing PyInstaller from local wheels...
    pip install --no-index --find-links="%~dp0pyinstaller_wheels" pyinstaller
    goto :build
)

REM Try online install
echo Trying online install...
pip install pyinstaller
if errorlevel 1 (
    echo.
    echo ============================================================
    echo Could not install PyInstaller.
    echo.
    echo Option A ^(no exe needed^):
    echo   Double-click run_gui.bat  — launches the GUI with Python directly.
    echo.
    echo Option B ^(portable single file, no exe^):
    echo   python build_pyz.py  — creates IO_Analysis.pyz + IO_Analysis.bat
    echo.
    echo Option C ^(offline exe^):
    echo   On a machine with internet access run:
    echo     pip download pyinstaller -d pyinstaller_wheels
    echo   Copy pyinstaller_wheels\ folder next to this script, then re-run.
    echo ============================================================
    pause
    exit /b 1
)

:build

echo.
echo Building executable...
python -m pyinstaller ^
    --name "IO_Analysis" ^
    --onefile ^
    --windowed ^
    --icon NONE ^
    --add-data "io_analysis;io_analysis" ^
    --hidden-import "io_analysis.config" ^
    --hidden-import "io_analysis.data.loader" ^
    --hidden-import "io_analysis.data.models" ^
    --hidden-import "io_analysis.analysis.analyzer" ^
    --hidden-import "io_analysis.plotting.plotter" ^
    --hidden-import "io_analysis.reporting.report_generator" ^
    --hidden-import "xml.etree.ElementTree" ^
    --hidden-import "zipfile" ^
    --hidden-import "csv" ^
    --hidden-import "tkinter" ^
    --hidden-import "tkinter.ttk" ^
    --hidden-import "tkinter.scrolledtext" ^
    --hidden-import "tkinter.filedialog" ^
    --hidden-import "tkinter.messagebox" ^
    gui_launcher.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED. See errors above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Build complete!
echo Executable: dist\IO_Analysis.exe
echo ============================================================
pause
