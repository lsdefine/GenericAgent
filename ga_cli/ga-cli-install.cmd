@echo off
chcp 65001 >nul
:: ga-cli-install.cmd - 将 GenericAgent 命令注册到系统 PATH
:: 运行一次后，即可在任意位置敲 ga <command>
:: 建议以管理员身份运行

cd /d "%~dp0.."
set "TARGET_DIR=%CD%"

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║      GenericAgent 命令行安装向导         ║
echo  ╚══════════════════════════════════════════╝
echo.
echo  项目目录: %TARGET_DIR%
echo.

REM 检查是否已在 PATH 中
echo %%PATH%% | find /I "%TARGET_DIR%" >nul
if not errorlevel 1 (
    echo  [✓] 项目目录已在 PATH 中
    echo  你可以在任意位置敲: ga list
    pause
    exit /b 0
)

set /p "YN=是否将项目目录添加到系统 PATH？(Y/n): "
if /I "%YN%"=="n" (
    echo  已取消
    pause
    exit /b 0
)

REM 尝试添加（需管理员权限）
for /f "skip=2 tokens=3*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "CURRENT_PATH=%%a %%b"
if not defined CURRENT_PATH (
    reg add "HKCU\Environment" /v PATH /t REG_EXPAND_SZ /d "%TARGET_DIR%" /f >nul
) else (
    rem 避免重复添加
    echo %%CURRENT_PATH%% | find /I "%TARGET_DIR%" >nul
    if errorlevel 1 (
        reg add "HKCU\Environment" /v PATH /t REG_EXPAND_SZ /d "%TARGET_DIR%;%CURRENT_PATH%" /f >nul
    )
)
if %errorlevel% equ 0 (
    echo  [✓] PATH 添加成功
) else (
    echo  [!] 添加失败，请以管理员身份运行
    pause
    exit /b 1
)

echo.
echo  ────────────────────────────────────────────
echo  安装完成！
echo.
echo  现在你可以：
echo    - 打开新的终端窗口
echo    - 在项目目录敲: ga list
echo    - 在任意位置敲: ga gui / ga web / ga hub ...
echo  ────────────────────────────────────────────
pause
