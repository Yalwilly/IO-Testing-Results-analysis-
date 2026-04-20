@echo off
cd /d "%~dp0"
python IO_Analysis.pyz %*
if errorlevel 1 pause
