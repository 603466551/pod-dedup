@echo off
setlocal
title POD Dedup - Startup Status
cd /d "%~dp0"
echo Starting POD Dedup...
echo.
powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_all.ps1"
