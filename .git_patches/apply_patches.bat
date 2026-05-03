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
    REM Stage all restored files (iterate copied files and git add them)
    for /r .git_patches\files %%F in (*) do (
        set "dst=%%F"
        setlocal enabledelayedexpansion
        set "dst=!dst:.git_patches\\files\\=!"
        endlocal & set "dst=%cd%\%dst%"
        git add "%dst%" >nul 2>nul || rem ignore failures
    )
    REM If any staged changes, commit them as a single restore commit
    git diff --cached --quiet 2>nul
    if errorlevel 1 (
        git commit -m "chore: restore files from .git_patches" >nul 2>nul || rem ignore
    )
)
for %%f in (".git_patches\*.patch") do (
    echo --------------------------------------------------
    echo Applying patch: %%~nxf
    git apply --index "%%f" 2>nul
    if errorlevel 1 (
        echo Failed to apply %%~nxf with git apply; skipping this patch.
    ) else (
        echo Applied %%~nxf via git apply --index
    )
)

echo All patches processed.
endlocal
exit /b 0
