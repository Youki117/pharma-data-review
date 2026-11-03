@echo off
cd /d "%~dp0"
python content_app.py
if errorlevel 1 pause
