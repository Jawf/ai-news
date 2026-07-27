@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\server.ps1" stop
pause
