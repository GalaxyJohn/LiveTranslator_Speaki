@echo off
setlocal

set "PYTHON=python"
if not "%~1"=="" set "PYTHON=%~1"

echo [1/3] Creating virtual environment...
%PYTHON% -m venv .venv
if errorlevel 1 goto :fail

echo [2/3] Upgrading pip...
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo [3/3] Installing runtime dependencies...
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Install complete.
echo Run app with: .venv\Scripts\python.exe main.py
exit /b 0

:fail
echo.
echo Install failed.
exit /b 1
