@echo off
chcp 65001 > nul
title Gemini Screen Translator - Executable Builder

echo ======================================================================
echo          Gemini Screen Translator - EXE Builder Script
echo ======================================================================
echo.

REM 1. Activate virtual environment if available
if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment from .venv...
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment from venv...
    call venv\Scripts\activate.bat
)

REM 2. Check Python installation
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python was not found in PATH or virtual environment!
    echo Please install Python 3.10+ and add it to your PATH.
    echo.
    pause
    exit /b 1
)

REM 3. Ensure PyInstaller is installed
python -m PyInstaller --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] PyInstaller is not installed. Installing now...
    pip install pyinstaller
)

REM 4. Clean up old build artifacts to guarantee a fresh compilation
echo [INFO] Cleaning up previous build artifacts...
if exist "build" (
    rmdir /s /q "build" >nul 2>&1
)
if exist "dist\GeminiScreenTranslator.exe" (
    del /f /q "dist\GeminiScreenTranslator.exe" >nul 2>&1
)

REM 5. Run PyInstaller compilation
echo [INFO] Compiling fresh standalone executable via PyInstaller...
echo [INFO] Running: python -m PyInstaller fordito.spec --noconfirm --clean
echo.

python -m PyInstaller fordito.spec --noconfirm --clean

if %ERRORLEVEL% neq 0 (
    echo.
    echo ======================================================================
    echo [ERROR] Build failed! Check the error log above for details.
    echo ======================================================================
    echo.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ======================================================================
echo [SUCCESS] Fresh executable created successfully!
echo ======================================================================
echo.
echo Output location: dist\GeminiScreenTranslator.exe
echo.
echo NOTE: Remember to copy your .env file into the dist folder or keep it
echo       in the working directory so the app can load your GEMINI_API_KEY.
echo.
pause
