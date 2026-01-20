@echo off
REM GoodGallery Launcher for Windows
REM Bootstraps portable Python if needed, then launches the app

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo    GoodGallery Launcher (Windows)
echo ============================================================
echo.

REM Define paths
set "ROOT_DIR=%~dp0"
set "RUNTIME_DIR=%ROOT_DIR%runtime"
set "PYTHON_DIR=%RUNTIME_DIR%\python-3.11.9"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "BOOTSTRAP_SCRIPT=%ROOT_DIR%bootstrap\launcher_core.py"

REM Check if portable Python exists
if exist "%PYTHON_EXE%" (
    echo [*] Using portable Python: %PYTHON_DIR%
    echo.
    goto :launch
)

REM Download portable Python
echo [*] Portable Python not found - downloading...
echo     This is a one-time setup (~30MB download)
echo.

REM Create runtime directory
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

REM Download using PowerShell
echo [*] Downloading Python 3.11.9 (Windows x64)...
set "PYTHON_URL=https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.11.9+20240107-x86_64-pc-windows-msvc-shared-install_only.tar.gz"
set "PYTHON_ARCHIVE=%RUNTIME_DIR%\python.tar.gz"

powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_ARCHIVE%' -UseBasicParsing}"

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to download Python
    echo Please check your internet connection and try again
    pause
    exit /b 1
)

echo [*] Download complete
echo.

REM Extract using PowerShell tar (Windows 10+) or 7-zip fallback
echo [*] Extracting Python...

REM Try Windows built-in tar first (Windows 10 1803+)
where tar >nul 2>&1
if %errorlevel% equ 0 (
    tar -xzf "%PYTHON_ARCHIVE%" -C "%RUNTIME_DIR%"
    if errorlevel 1 (
        echo [ERROR] Extraction failed
        pause
        exit /b 1
    )
) else (
    REM Fallback to PowerShell extraction
    powershell -Command "& {Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%PYTHON_ARCHIVE%', '%RUNTIME_DIR%')}"
)

REM Rename extracted directory to expected name
for /d %%d in ("%RUNTIME_DIR%\python*") do (
    if not "%%d"=="%PYTHON_DIR%" (
        move "%%d" "%PYTHON_DIR%" >nul 2>&1
    )
)

REM Clean up archive
del "%PYTHON_ARCHIVE%" >nul 2>&1

if exist "%PYTHON_EXE%" (
    echo [*] Python extracted successfully
    echo.
) else (
    echo [ERROR] Python extraction failed
    echo Expected: %PYTHON_EXE%
    pause
    exit /b 1
)

:launch
REM Launch bootstrap script
echo [*] Starting GoodGallery bootstrap...
echo.

"%PYTHON_EXE%" "%BOOTSTRAP_SCRIPT%"

if errorlevel 1 (
    echo.
    echo [ERROR] GoodGallery failed to start
    pause
    exit /b 1
)

endlocal
