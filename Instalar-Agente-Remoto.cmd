@echo off
rem Doble clic para instalar el agente del MCP remoto (Claude en Excel) y dejarlo en segundo plano.
title Instalar agente remoto ApuRisk
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-agent.ps1" %*
echo.
pause
