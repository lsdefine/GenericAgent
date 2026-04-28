@echo off
cd /d "%~dp0"
setlocal
:: One-click entry: ensure LiteLLM ready, then launch UI once.
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "LITELLM_PORT=8000"

if "%GA_PROXY_MODE%"=="" set "GA_PROXY_MODE=auto"
if "%GA_PROXY_URL%"=="" set "GA_PROXY_URL=http://127.0.0.1:6789"

if not exist "%PYTHON_EXE%" (
	echo [ERROR] .venv not found. Please create virtual environment first.
	echo         python -m venv .venv
	exit /b 1
)

for /f %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$all=Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" -ErrorAction SilentlyContinue; $cnt=($all.Where({ $_.CommandLine -like '*frontends\\stapp.py*' -or $_.CommandLine -like '*frontends\\fsapp.py*' })).Count; Write-Output $cnt"') do set "GA_RUNNING_COUNT=%%i"
if not "%GA_RUNNING_COUNT%"=="0" (
	echo [INFO] GenericAgent services are already running ^(stapp/fsapp detected^). Skipping duplicate startup.
	exit /b 0
)

echo [INFO] Checking LiteLLM on port %LITELLM_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:%LITELLM_PORT%/v1/models' -TimeoutSec 2 -UseBasicParsing; if ($resp.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
	echo [INFO] LiteLLM not ready. Starting start_litellm.bat in a new window...
	echo [INFO] Proxy settings: GA_PROXY_MODE=%GA_PROXY_MODE%, GA_PROXY_URL=%GA_PROXY_URL%
	start "GenericAgent LiteLLM" cmd /c start_litellm.bat
	echo [WARN] LiteLLM is starting in background. UI will launch now.
)

set "PYTHONEXECUTABLE=%PYTHON_EXE%"
start "GenericAgent UI" "%PYTHON_EXE%" launch.pyw --feishu
exit /b 0