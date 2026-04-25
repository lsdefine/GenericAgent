@echo off
cd /d "%~dp0"
setlocal

set "LITELLM_PORT=8000"
if "%GA_PROXY_MODE%"=="" set "GA_PROXY_MODE=auto"
if "%GA_PROXY_URL%"=="" set "GA_PROXY_URL=http://127.0.0.1:6789"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Please create virtual environment first.
  echo         python -m venv .venv
  exit /b 1
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo [ERROR] Failed to activate .venv
  exit /b 1
)

if "%GITHUB_COPILOT_TOKEN%"=="" (
  for /f "usebackq delims=" %%i in (`gh auth token 2^>nul`) do set "GITHUB_COPILOT_TOKEN=%%i"
)

if "%GITHUB_COPILOT_TOKEN%"=="" (
  echo [ERROR] GITHUB_COPILOT_TOKEN is not set.
  echo         Please run `gh auth login --scopes copilot` or set the environment variable manually.
  exit /b 1
)

set "GA_PROXY_ACTIVE=0"
if /I "%GA_PROXY_MODE%"=="off" (
  set "GA_PROXY_ACTIVE=0"
) else if /I "%GA_PROXY_MODE%"=="on" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$u=[uri]$env:GA_PROXY_URL; $c=New-Object Net.Sockets.TcpClient; try { $ar=$c.BeginConnect($u.Host,$u.Port,$null,$null); if(-not $ar.AsyncWaitHandle.WaitOne(1200)){ exit 1 }; $c.EndConnect($ar); exit 0 } catch { exit 1 } finally { $c.Close() }"
  if errorlevel 1 (
    echo [ERROR] GA_PROXY_MODE=on but proxy is unreachable: %GA_PROXY_URL%
    exit /b 1
  )
  set "GA_PROXY_ACTIVE=1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$u=[uri]$env:GA_PROXY_URL; $c=New-Object Net.Sockets.TcpClient; try { $ar=$c.BeginConnect($u.Host,$u.Port,$null,$null); if(-not $ar.AsyncWaitHandle.WaitOne(1200)){ exit 1 }; $c.EndConnect($ar); exit 0 } catch { exit 1 } finally { $c.Close() }"
  if not errorlevel 1 set "GA_PROXY_ACTIVE=1"
)

if "%GA_PROXY_ACTIVE%"=="1" (
  set "HTTP_PROXY=%GA_PROXY_URL%"
  set "HTTPS_PROXY=%GA_PROXY_URL%"
  set "ALL_PROXY=%GA_PROXY_URL%"
  set "NO_PROXY=127.0.0.1,localhost"
  echo [INFO] Proxy mode=%GA_PROXY_MODE% ^(active^): %GA_PROXY_URL%
) else (
  set "HTTP_PROXY="
  set "HTTPS_PROXY="
  set "ALL_PROXY="
  set "NO_PROXY=*"
  echo [INFO] Proxy mode=%GA_PROXY_MODE% ^(direct^)
)

if not exist ".venv\Scripts\litellm.exe" (
  echo [INFO] LiteLLM not found in .venv, installing...
  .venv\Scripts\python.exe -m pip install "litellm[proxy]"
  if errorlevel 1 (
    echo [ERROR] Failed to install litellm in .venv
    exit /b 1
  )
)

if exist ".venv\Scripts\python.exe" if exist "verify_copilot_models.py" (
  echo [INFO] Syncing available Copilot models into config...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$conn = Get-NetTCPConnection -LocalPort %LITELLM_PORT% -State Listen -ErrorAction SilentlyContinue; if ($conn) { $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }" >nul 2>nul
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -WindowStyle Hidden -FilePath '%CD%\.venv\Scripts\litellm.exe' -ArgumentList '--config','litellm_config.yaml','--port','%LITELLM_PORT%'"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ready = $false; for ($i = 0; $i -lt 40; $i++) { try { $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:%LITELLM_PORT%/v1/models' -TimeoutSec 2 -UseBasicParsing; if ($resp.StatusCode -eq 200) { $ready = $true; break } } catch {}; Start-Sleep -Milliseconds 500 }; if (-not $ready) { exit 1 }"
  if errorlevel 1 (
    echo [ERROR] Bootstrap LiteLLM failed to start.
    exit /b 1
  )
  .venv\Scripts\python.exe verify_copilot_models.py --apply
  if errorlevel 1 (
    echo [ERROR] Failed to refresh available Copilot models.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$conn = Get-NetTCPConnection -LocalPort %LITELLM_PORT% -State Listen -ErrorAction SilentlyContinue; if ($conn) { $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }" >nul 2>nul
    exit /b 1
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$conn = Get-NetTCPConnection -LocalPort %LITELLM_PORT% -State Listen -ErrorAction SilentlyContinue; if ($conn) { $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }" >nul 2>nul
)

echo [INFO] Starting LiteLLM on port 8000 using .venv
.venv\Scripts\litellm.exe --config litellm_config.yaml --port %LITELLM_PORT%
