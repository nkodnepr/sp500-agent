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
rem  The build runs inside its own throwaway virtual environment
rem  (build-venv) instead of the system Python. A system-wide
rem  numpy/pandas of a different version can be picked up by
rem  PyInstaller and produce an .exe that dies at startup with
rem  "DLL load failed while importing _multiarray_umath" - a clean
rem  isolated environment removes that whole class of failure.
rem
rem  Result: dist\StockAgent.exe
rem ============================================================

cd /d "%~dp0"
echo Working directory: %CD%
echo.

rem --- Locate a REAL Python install (not the Windows Store stub) ---
set PYTHON_CMD=
set VENV_DIR=build-venv

rem Prefer the version pinned in runtime.txt (same one CI builds with)
py -3.13 --version >nul 2>nul
if not errorlevel 1 (
    set PYTHON_CMD=py -3.13
    goto :found_python
)

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

if not exist "requirements-desktop.txt" (
    echo [ERROR] requirements-desktop.txt not found in this folder.
    echo Make sure this .bat file is in the SAME folder as the
    echo project files ^(build_exe.py, requirements.txt, etc^),
    echo not in a subfolder or a different location after unzipping.
    echo.
    pause
    exit /b 1
)

rem --- Always build in a FRESH isolated environment ---
rem Deleting any previous build-venv guarantees the build never inherits
rem a half-installed or binary-incompatible package from an earlier
rem attempt, and never touches the system Python at all.
if exist "%VENV_DIR%" (
    echo Removing the previous build environment for a clean rebuild...
    rmdir /s /q "%VENV_DIR%"
)

echo Creating a clean build environment...
%PYTHON_CMD% -m venv %VENV_DIR%
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to create the build environment.
    echo.
    pause
    exit /b 1
)

echo Installing build dependencies - this can take a few minutes...
echo (progress will print below; please wait, do not close this window)
echo.
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements-desktop.txt -r requirements-build.txt
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
"%VENV_DIR%\Scripts\python.exe" build_exe.py

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
