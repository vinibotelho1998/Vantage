@echo off
title DBX Stats - Instalacao automatica
echo.
echo   Iniciando a instalacao do DBX Stats...
echo   (vai pedir permissao de administrador)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
