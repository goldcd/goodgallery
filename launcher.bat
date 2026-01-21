@echo off
REM GoodGallery Launcher for Windows
REM Bootstraps portable Python if needed, then launches the app

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo    GoodGallery Launcher (Windows)
echo ============================================================
echo.

echo.

REM Define paths
set "ROOT_DIR=%~dp0"
set "RUNTIME_DIR=%ROOT_DIR%runtime"
set "PYTHON_DIR=%RUNTIME_DIR%\python-3.11.9"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PIP_EXE=%PYTHON_DIR%\Scripts\pip.exe"
set "BOOTSTRAP_SCRIPT=%ROOT_DIR%bootstrap\launcher_core.py"

REM Check for Python
if exist "%PYTHON_EXE%" (
    echo [*] Found portable Python: %PYTHON_DIR%
) else (
    goto :download_python
)

REM Check for Pip (repair if needed)
if not exist "%PIP_EXE%" (
    echo [!] Python found but pip is missing. repairing...
    goto :install_pip
)

goto :launch

:download_python
REM Download portable Python
echo [*] Portable Python not found - downloading...
echo     This is a one-time setup (~30MB download)
echo.

REM Create runtime directory
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

REM Download using PowerShell
echo [*] Downloading Python 3.11.9 (Windows x64)...
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
set "PYTHON_ARCHIVE=%RUNTIME_DIR%\python.zip"

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

REM Extract using PowerShell
echo [*] Extracting Python...
powershell -Command "& {Expand-Archive -Path '%PYTHON_ARCHIVE%' -DestinationPath '%PYTHON_DIR%' -Force}"

if errorlevel 1 (
    echo [ERROR] Extraction failed
    pause
    exit /b 1
)

REM Clean up archive
del "%PYTHON_ARCHIVE%" >nul 2>&1

:install_pip
REM Install pip into embedded Python
echo [*] Installing pip...
powershell -Command "& {Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%PYTHON_DIR%\get-pip.py' -UseBasicParsing}"
"%PYTHON_DIR%\python.exe" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location

REM Enable site-packages by removing import restriction
echo [*] Configuring Python...
powershell -Command "& {(Get-Content '%PYTHON_DIR%\python311._pth') -replace '#import site', 'import site' | Set-Content '%PYTHON_DIR%\python311._pth'}"


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
