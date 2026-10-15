@echo off
cd /d "%~dp0"
python -B browser.py
if errorlevel 1 pause
