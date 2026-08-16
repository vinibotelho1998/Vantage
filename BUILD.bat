@echo off
title DBX Stats - gerar instalador
echo.
echo   Gerando o instalador do DBX Stats.
echo   O resultado sai em dist\DBXStats-Setup.exe
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build.ps1"
pause
