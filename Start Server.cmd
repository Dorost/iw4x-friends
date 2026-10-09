@echo off
rem Double-click to start the IW4x server web UI (Windows).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\windows\start-ui.ps1"
pause
