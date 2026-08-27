@echo off
title Dbx Stats - gerar instalador
echo.
echo   Gerando o instalador do Dbx Stats.
echo   O resultado sai em dist\DbxStats-Setup.exe
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build.ps1"
pause
