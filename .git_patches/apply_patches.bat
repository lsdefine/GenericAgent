@echo off
REM 一键应用补丁到工作区（按字典序）
REM 使用前请确保在仓库根目录运行，并且已提交或 stash 本地改动

setlocal enabledelayedexpansion
cd /d %~dp0\..
if not exist .git (
    echo This directory is not a git repository.
    exit /b 1
)

echo Applying patches from .git_patches\ ...
REM First: restore any full-file backups under .git_patches\files
if exist .git_patches\files (
    echo Restoring files from .git_patches\files ...
    for /r .git_patches\files %%F in (*) do (
        set "src=%%~fF"
        set "rel=%%~pF"
        REM remove leading \ from rel and .git_patches\files\ prefix
        set "rel=%%F:.git_patches\\files\\=%"
        REM ensure destination directory exists
        for %%I in ("%%~dpF") do set "d=%%~fI"
        REM compute destination path
        set "dst=%cd%\%%F:.git_patches\\files\\=%"
        xcopy "%%~fF" "%%~dpF\..\..\..\.." >nul 2>nul
    )
    REM Stage restored files
    git add .git_patches\files\* >nul 2>nul || true
)
for %%f in (".git_patches\*.patch") do (
    echo --------------------------------------------------
    echo Applying patch: %%~nxf
    git apply --index "%%f" 2>nul
    if errorlevel 1 (
        echo Failed to apply %%~nxf with git apply; trying git am fallback...
        git am --abort >nul 2>nul
        git am "%%f"
        if errorlevel 1 (
            echo ERROR: git am failed for %%~nxf, aborting.
            exit /b 2
        ) else (
            echo Applied %%~nxf via git am
        )
    ) else (
        echo Applied %%~nxf via git apply --index
    )
)

echo All patches processed.
endlocal
exit /b 0
