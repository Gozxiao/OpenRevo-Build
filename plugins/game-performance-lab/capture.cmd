@echo off
chcp 65001 >nul
title OpenRevo Game Performance Lab - Intel PresentMon
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-capture.ps1"
echo.
echo Press any key to close...
pause >nul
