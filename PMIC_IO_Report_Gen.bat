@echo off
cd /d "%~dp0"
python PMIC_IO_Report_Gen.pyz %*
if errorlevel 1 pause
