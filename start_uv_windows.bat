@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

title GenericAgent（uv）启动器
color 0A

echo.
echo ========================================
echo   GenericAgent Windows 版 uv 启动器
echo ========================================
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo [错误] 未在 PATH 中找到 uv。
    echo 请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/
    echo.
    pause
    exit /b 1
)

if not exist "pyproject.toml" (
    echo [错误] 未找到 pyproject.toml。请将此脚本放在项目根目录中。
    echo.
    pause
    exit /b 1
)

set "PROJECT_PYTHON=3.12"
set "INSTALL_MODE=ui"
set "RUN_MODE="
set "RUN_DESC="
set "RUN_CMD="

if not exist "mykey.py" (
    if exist "mykey_template.py" (
        copy /Y "mykey_template.py" "mykey.py" >nul
        echo [信息] 未找到 mykey.py，已根据 mykey_template.py 自动创建。
        echo [信息] 正常使用前，请先编辑 mykey.py 并填入你的 API 配置。
        echo.
    ) else (
        echo [警告] 缺少 mykey.py，且未找到 mykey_template.py。
        echo.
    )
)

call :select_mode
if errorlevel 1 exit /b 1

call :ensure_venv
if errorlevel 1 goto :uv_failed

call :install_deps
if errorlevel 1 goto :uv_failed

call :launch
exit /b %ERRORLEVEL%

:select_mode
echo 请选择启动方式：
echo.
echo   [1] 默认桌面 GUI ^(launch.pyw + Streamlit + pywebview^)
echo   [2] 终端 UI ^(frontends\tuiapp.py^)
echo   [3] Qt 桌面应用 ^(frontends\qtapp.py^)
echo   [4] Streamlit 网页界面 ^(frontends\stapp2.py^)
echo   [5] 微信 Bot ^(frontends\wechatapp.py^)
echo   [6] QQ Bot ^(frontends\qqapp.py^)
echo   [7] 飞书 Bot ^(frontends\fsapp.py^)
echo   [8] 企业微信 Bot ^(frontends\wecomapp.py^)
echo   [9] 钉钉 Bot ^(frontends\dingtalkapp.py^)
echo   [0] 退出
echo.
set /p "CHOICE=请输入编号并回车： "
set "CHOICE=%CHOICE: =%"
echo.

if "%CHOICE%"=="1" (
    set "INSTALL_MODE=ui"
    set "RUN_MODE=desktop"
    set "RUN_DESC=默认桌面 GUI"
    set "RUN_CMD=python launch.pyw"
    exit /b 0
)
if "%CHOICE%"=="2" (
    set "INSTALL_MODE=ui"
    set "RUN_MODE=tui"
    set "RUN_DESC=终端 UI"
    set "RUN_CMD=python frontends\tuiapp.py"
    exit /b 0
)
if "%CHOICE%"=="3" (
    set "INSTALL_MODE=qt"
    set "RUN_MODE=qt"
    set "RUN_DESC=Qt 桌面应用"
    set "RUN_CMD=python frontends\qtapp.py"
    exit /b 0
)
if "%CHOICE%"=="4" (
    set "INSTALL_MODE=ui"
    set "RUN_MODE=stapp2"
    set "RUN_DESC=Streamlit 网页界面"
    set "RUN_CMD=streamlit run frontends\stapp2.py"
    exit /b 0
)
if "%CHOICE%"=="5" (
    set "INSTALL_MODE=wechat"
    set "RUN_MODE=wechat"
    set "RUN_DESC=微信 Bot"
    set "RUN_CMD=python frontends\wechatapp.py"
    exit /b 0
)
if "%CHOICE%"=="6" (
    set "INSTALL_MODE=all-frontends"
    set "RUN_MODE=qq"
    set "RUN_DESC=QQ Bot"
    set "RUN_CMD=python frontends\qqapp.py"
    exit /b 0
)
if "%CHOICE%"=="7" (
    set "INSTALL_MODE=all-frontends"
    set "RUN_MODE=feishu"
    set "RUN_DESC=飞书 Bot"
    set "RUN_CMD=python frontends\fsapp.py"
    exit /b 0
)
if "%CHOICE%"=="8" (
    set "INSTALL_MODE=all-frontends"
    set "RUN_MODE=wecom"
    set "RUN_DESC=企业微信 Bot"
    set "RUN_CMD=python frontends\wecomapp.py"
    exit /b 0
)
if "%CHOICE%"=="9" (
    set "INSTALL_MODE=all-frontends"
    set "RUN_MODE=dingtalk"
    set "RUN_DESC=钉钉 Bot"
    set "RUN_CMD=python frontends\dingtalkapp.py"
    exit /b 0
)
if "%CHOICE%"=="0" (
    echo 已取消启动。
    exit /b 1
)

echo [错误] 无效选项：%CHOICE%
echo.
pause
exit /b 1

:ensure_venv
if not exist ".venv\Scripts\python.exe" (
    echo [步骤] 正在使用 uv 管理的 Python %PROJECT_PYTHON% 创建虚拟环境...
    call uv venv --python %PROJECT_PYTHON%
    if errorlevel 1 (
        echo [步骤] uv venv 无法自动准备 Python，正在尝试执行 uv python install %PROJECT_PYTHON%...
        call uv python install %PROJECT_PYTHON%
        if errorlevel 1 exit /b 1
        call uv venv --python %PROJECT_PYTHON%
        if errorlevel 1 exit /b 1
    )
    echo.
)
exit /b 0

:install_deps
if "%INSTALL_MODE%"=="ui" goto :install_ui
if "%INSTALL_MODE%"=="qt" goto :install_qt
if "%INSTALL_MODE%"=="wechat" goto :install_wechat
if "%INSTALL_MODE%"=="all-frontends" goto :install_all_frontends
exit /b 0

:install_ui
if exist "uv.lock" (
    echo [步骤] 正在根据 uv.lock 同步依赖 ^(额外依赖：ui^) ...
    call uv sync --extra ui
    if not errorlevel 1 (
        echo.
        exit /b 0
    )
    echo [警告] uv sync 失败，正在回退到安装命令...
    echo.
)

echo [步骤] 正在安装项目依赖 ^(可编辑安装 + ui 额外依赖^) ...
call uv pip install -e ".\.[ui]"
if errorlevel 1 exit /b 1
echo.
exit /b 0

:install_qt
call :install_ui
if errorlevel 1 exit /b 1
echo [步骤] 正在安装 Qt 前端依赖 ^(PySide6^) ...
call uv pip install PySide6
if errorlevel 1 exit /b 1
echo.
exit /b 0

:install_wechat
echo [步骤] 正在安装微信 Bot 依赖 ...
call uv pip install requests pycryptodome qrcode
if errorlevel 1 exit /b 1
echo.
exit /b 0

:install_all_frontends
echo [步骤] 正在安装 Bot 所需依赖 ^(all-frontends 额外依赖^) ...
call uv pip install -e ".\.[all-frontends]"
if errorlevel 1 exit /b 1
echo.
exit /b 0

:launch
echo [步骤] 正在启动 %RUN_DESC%...
echo [命令] %RUN_CMD%
echo.

if "%RUN_MODE%"=="desktop" (
    call uv run --python .venv\Scripts\python.exe python launch.pyw
) else if "%RUN_MODE%"=="tui" (
    call uv run --python .venv\Scripts\python.exe python frontends\tuiapp.py
) else if "%RUN_MODE%"=="qt" (
    call uv run --python .venv\Scripts\python.exe python frontends\qtapp.py
) else if "%RUN_MODE%"=="stapp2" (
    call uv run --python .venv\Scripts\python.exe streamlit run frontends\stapp2.py
) else if "%RUN_MODE%"=="wechat" (
    call uv run --python .venv\Scripts\python.exe python frontends\wechatapp.py
) else if "%RUN_MODE%"=="qq" (
    call uv run --python .venv\Scripts\python.exe python frontends\qqapp.py
) else if "%RUN_MODE%"=="feishu" (
    call uv run --python .venv\Scripts\python.exe python frontends\fsapp.py
) else if "%RUN_MODE%"=="wecom" (
    call uv run --python .venv\Scripts\python.exe python frontends\wecomapp.py
) else if "%RUN_MODE%"=="dingtalk" (
    call uv run --python .venv\Scripts\python.exe python frontends\dingtalkapp.py
) else (
    echo [错误] 未知启动模式：%RUN_MODE%
    exit /b 1
)

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [错误] GenericAgent 已退出，退出代码为 %EXIT_CODE%。
    pause
)
exit /b %EXIT_CODE%

:uv_failed
echo.
echo [错误] uv 未能完成环境准备。
echo [提示] 此启动器不要求系统 PATH 中预先存在 python。
echo [提示] 需要时，它会让 uv 自动准备 Python %PROJECT_PYTHON%。
echo [提示] 如果仍然失败，请检查网络连接后重试，或手动执行：uv python install %PROJECT_PYTHON%
echo.
pause
exit /b 1
