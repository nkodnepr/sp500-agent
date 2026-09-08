@echo off
setlocal enabledelayedexpansion

rem UTF-8 console: the app logs Russian text
chcp 65001 >nul

rem ============================================================
rem  Stock Agent - run the desktop app (Windows)
rem  Just double-click this file.
rem
rem  First run: creates a virtual environment and installs
rem  dependencies - takes a few minutes. Later runs are fast.
rem
rem  Requires Python installed from python.org (check "Add
rem  python.exe to PATH" during install). If you don't want
rem  Python on this PC at all, use build_windows.bat instead.
rem ============================================================

cd /d "%~dp0"
echo Working directory: %CD%
echo.

set VENV_DIR=venv
set MARKER_FILE=%VENV_DIR%\.deps_installed

rem --- Locate a REAL Python install (not the Windows Store stub) ---
set PYTHON_CMD=

py --version >nul 2>nul
if not errorlevel 1 (
    set PYTHON_CMD=py
    goto :found_python
)

python --version >nul 2>nul
if not errorlevel 1 (
    set PYTHON_CMD=python
    goto :found_python
)

echo [ERROR] Python was not found.
echo.
echo If a Microsoft Store window just opened - that means Python is
echo NOT actually installed on this PC (Windows shows a fake "python"
echo command that only opens the Store). Close the Store window and
echo install Python for real from: https://www.python.org/downloads/
echo During install, check the box "Add python.exe to PATH".
echo Then run this file again.
echo.
pause
exit /b 1

:found_python
echo Found Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

if not exist "desktop_app.py" (
    echo [ERROR] desktop_app.py not found in this folder.
    echo Make sure this .bat file is in the SAME folder as the
    echo project files, not in a subfolder or different location.
    echo.
    pause
    exit /b 1
)

rem --- Create venv on first run ---
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo First run - creating virtual environment...
    %PYTHON_CMD% -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

rem --- Install dependencies once, marked by MARKER_FILE ---
if not exist "%MARKER_FILE%" (
    echo Installing dependencies - this can take a few minutes...
    echo (progress will print below; please wait)
    echo.
    "%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
    "%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements-desktop.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies.
        echo Check your internet connection and run this file again.
        echo.
        pause
        exit /b 1
    )
    echo done > "%MARKER_FILE%"
    echo Dependencies installed.
    echo.
)

echo Starting Stock Agent...
echo.
"%VENV_DIR%\Scripts\python.exe" desktop_app.py

if errorlevel 1 (
    echo.
    echo [ERROR] The program exited with an error - see above.
    pause
)

endlocal
