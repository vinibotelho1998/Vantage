@echo off
title Vantage - gerar instalador
echo.
echo   Gerando o instalador do Vantage.
echo   O resultado sai em dist\Vantage-Setup.exe
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build.ps1"
pause
