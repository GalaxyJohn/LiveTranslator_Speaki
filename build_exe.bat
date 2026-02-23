@echo off
setlocal

set "PYTHON=python"
if not "%~1"=="" set "PYTHON=%~1"

powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1 -Python "%PYTHON%" -Clean
exit /b %errorlevel%
