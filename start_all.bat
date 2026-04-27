@echo off
chcp 65001 >nul 2>&1  :: 设置 UTF-8 代码页
cd /d "%~dp0"
setlocal

set "LITELLM_PORT=8000"
set "WAIT_SECONDS=60"
set "LITELLM_READY=0"

if "%GA_PROXY_MODE%"=="" set "GA_PROXY_MODE=auto"
if "%GA_PROXY_URL%"=="" set "GA_PROXY_URL=http://127.0.0.1:6789"
echo [INFO] Proxy settings for LiteLLM: GA_PROXY_MODE=%GA_PROXY_MODE%, GA_PROXY_URL=%GA_PROXY_URL%
echo [INFO] 当前已以管理员权限运行

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Please create virtual environment first.
  echo         python -m venv .venv
  exit /b 1
)

echo [INFO] Checking whether LiteLLM is already running on port %LITELLM_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:%LITELLM_PORT%/v1/models' -TimeoutSec 2 -UseBasicParsing; if ($resp.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 set "LITELLM_READY=1"

if "%LITELLM_READY%"=="1" (
  echo [INFO] LiteLLM is already available. Skipping duplicate startup.
) else (
  echo [INFO] LiteLLM is not running. Starting LiteLLM bootstrap in a separate window...
  start "GenericAgent LiteLLM" cmd /c start_litellm.bat
)

echo [INFO] Waiting for LiteLLM on port %LITELLM_PORT% to become ready ^(up to %WAIT_SECONDS% seconds^)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ready = $false; for ($i = 0; $i -lt %WAIT_SECONDS%; $i++) { try { $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:%LITELLM_PORT%/v1/models' -TimeoutSec 2 -UseBasicParsing; if ($resp.StatusCode -eq 200) { $ready = $true; break } } catch {}; Start-Sleep -Seconds 1 }; if (-not $ready) { exit 1 }"
if errorlevel 1 (
  echo [ERROR] LiteLLM was not ready within %WAIT_SECONDS% seconds.
  echo         If a LiteLLM window opened, check that window for details.
  exit /b 1
)

echo [INFO] LiteLLM is ready. Launching GenericAgent UI...
call start.bat