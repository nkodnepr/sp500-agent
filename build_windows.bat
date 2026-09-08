@echo off
setlocal

rem UTF-8 console: the build script prints Russian text, which crashes
rem on the default codepage of cmd.exe
chcp 65001 >nul

rem ============================================================
rem  Stock Agent - build standalone StockAgent.exe (Windows)
rem  Double-click this file. Python is required ONLY for the
rem  build step - the resulting .exe will not need Python at all.
rem
rem  Result: dist\StockAgent.exe
rem ============================================================

cd /d "%~dp0"
echo Working directory: %CD%
echo.

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

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found in this folder.
    echo Make sure this .bat file is in the SAME folder as the
    echo project files ^(build_exe.py, requirements.txt, etc^),
    echo not in a subfolder or a different location after unzipping.
    echo.
    pause
    exit /b 1
)

echo Installing build dependencies - this can take a few minutes...
echo (progress will print below; please wait, do not close this window)
echo.
%PYTHON_CMD% -m pip install --upgrade pip
%PYTHON_CMD% -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed - see errors above.
    echo Check your internet connection and try again.
    echo.
    pause
    exit /b 1
)

echo.
echo Building StockAgent.exe - this usually takes several minutes...
echo.
%PYTHON_CMD% build_exe.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed - see errors above.
    echo.
    pause
    exit /b 1
)

echo.
echo ===============================================
echo  Done! File: dist\StockAgent.exe
echo  Copy it anywhere and double-click to run -
echo  Python is not required on the target PC anymore.
echo ===============================================
pause
endlocal
