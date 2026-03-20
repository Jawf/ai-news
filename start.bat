@echo off
cd /d "%~dp0"
uv run python main.py
if errorlevel 1 pause
