@echo off
rem Doble clic para instalar el servidor MCP y el skill de ApuRisk en Claude Code.
title Instalar ApuRisk MCP
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
