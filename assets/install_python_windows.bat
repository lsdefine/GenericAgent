@echo off
setlocal enabledelayedexpansion
title Python One-Click Installer
color 0A

echo.
echo ========================================
echo    Python One-Click Installer (Windows)
echo ========================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Administrator privileges required. Restarting with elevation...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo [OK] Administrator privileges confirmed
echo.

python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python already installed:
    python --version
    echo.
    choice /C YN /M "Install latest version anyway? (Y=Yes / N=Exit)"
    if errorlevel 2 goto :end
)

set PYTHON_VERSION=3.12.9
set MIRROR_URL=https://npmmirror.com/mirrors/python/3.12.9/python-3.12.9-amd64.exe
set OFFICIAL_URL=https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe
set INSTALLER=%TEMP%\python_installer.exe

echo [*] Preparing to download Python %PYTHON_VERSION%
echo [*] Trying mirror source first...
echo.

powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%MIRROR_URL%' -OutFile '%INSTALLER%' -UseBasicParsing"

if not exist "%INSTALLER%" goto :official
for %%A in ("%INSTALLER%") do if %%~zA lss 1000000 goto :official
echo [OK] Mirror download complete
goto :install

:official
echo [!] Mirror failed, switching to official source...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%OFFICIAL_URL%' -OutFile '%INSTALLER%' -UseBasicParsing"

if not exist "%INSTALLER%" (
    echo [x] Download failed. Please check your network connection and retry.
    pause
    goto :end
)
for %%A in ("%INSTALLER%") do if %%~zA lss 1000000 (
    echo [x] Downloaded file is incomplete. Please check your network and retry.
    pause
    goto :end
)
echo [OK] Official source download complete

:install
echo.
echo [*] Installing Python %PYTHON_VERSION% (this may take 2-5 minutes^)...
echo.

start /wait "" "%INSTALLER%" /passive InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1

set INSTALL_CODE=%errorlevel%
del /f /q "%INSTALLER%" >nul 2>&1

if %INSTALL_CODE% neq 0 (
    echo [x] Installation failed with error code: %INSTALL_CODE%
    pause
    goto :end
)

echo [+] Installation complete!
echo.

timeout /t 3 /nobreak >nul

set "PATH=C:\Program Files\Python312;C:\Program Files\Python312\Scripts;%PATH%"

python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python installed successfully:
    python --version
    echo.
    echo [OK] pip version:
    pip --version
    echo.
    echo [*] Configuring pip mirror (Tsinghua^)...
    pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
    pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
    echo.
    echo [*] Installing requests...
    pip install requests
    echo.
    echo ========================================
    echo    All done! Open a new terminal to use
    echo    python and pip commands.
    echo ========================================
) else (
    echo [!] PATH not yet refreshed. Please close this window and open a new terminal.
)

:end
echo.
pause
