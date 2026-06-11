#requires -version 5.1

<#!

GenericAgent one-click portable deployer for Windows.



Modes:

  Default/Mainland: download GenericAgent.zip + uv + PortableGit from user's VPS, set China PyPI mirror.

  GLOBAL=1: clone GenericAgent from GitHub; uv and PortableGit also come from GitHub releases; no PyPI mirror.



Portable components are installed under <InstallDir>\.portable:

  uv, Python installed by uv, PortableGit.

#>

param(

    [string]$InstallDir = "$env:USERPROFILE\GenericAgent",

    [string]$PythonVersion = "3.12",

    [switch]$Force

)



$ErrorActionPreference = "Stop"



# Make Chinese output reliable in Windows PowerShell 5.1 and redirected logs.

try {

    [Console]::InputEncoding = [System.Text.Encoding]::UTF8

    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

    $OutputEncoding = [System.Text.Encoding]::UTF8

} catch { }



$RepoUrl = "https://github.com/lsdefine/GenericAgent.git"

$VpsBase = "http://47.101.182.29:9000"

$GaZipUrl = "$VpsBase/files/GenericAgent.zip"

$UvUrl = "$VpsBase/uv/uv-x86_64-pc-windows-msvc.zip"

$GitUrl = "$VpsBase/files/PortableGit-2.54.0-64-bit.7z.exe"

$Deps = @("requests>=2.28", "beautifulsoup4>=4.12", "bottle>=0.12", "simple-websocket-server>=0.4", "streamlit>=1.28")

$MainlandIndex = "https://pypi.tuna.tsinghua.edu.cn/simple"

$GlobalMode = ($env:GLOBAL -eq "1")

if ($GlobalMode) {
    # GLOBAL=1: fetch everything from GitHub; no mainland endpoints involved.
    $UvUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    $GitUrl = "https://github.com/git-for-windows/git/releases/download/v2.54.0.windows.1/PortableGit-2.54.0-64-bit.7z.exe"
}



$GaDir = [IO.Path]::GetFullPath($InstallDir)

$PortableRoot = Join-Path $GaDir ".portable"

$Bin = Join-Path $PortableRoot "bin"

$Cache = Join-Path $PortableRoot "cache"

$Tools = Join-Path $PortableRoot "tools"

$UvZip = Join-Path $Cache "uv-x86_64-pc-windows-msvc.zip"

$GaZip = Join-Path $Cache "GenericAgent.zip"

$GitExeArchive = Join-Path $Cache "PortableGit-2.54.0-64-bit.7z.exe"

$UvExtract = Join-Path $Cache "uv-extract"

$GaExtract = Join-Path $Cache "ga-extract"

$GitDir = Join-Path $Tools "PortableGit"

$UvExe = Join-Path $Bin "uv.exe"

$GitExe = Join-Path $GitDir "bin\git.exe"

$EnvCmd = Join-Path $GaDir "env.cmd"

$EnvPs1 = Join-Path $GaDir "env.ps1"



function Say($m) { Write-Host "[ga-deploy] $m" -ForegroundColor Cyan }

function Ok($m) { Write-Host "[ok] $m" -ForegroundColor Green }

function Die($m) { Write-Host "[error] $m" -ForegroundColor Red; exit 1 }

function Invoke-Native([scriptblock]$Command) {

    $prevEAP = $ErrorActionPreference

    $ErrorActionPreference = 'Continue'

    try { & $Command } finally { $ErrorActionPreference = $prevEAP }

    return $LASTEXITCODE

}



function Download-File($Url, $OutFile) {

    New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null

    Say "Downloading $Url"

    $wc = New-Object System.Net.WebClient

    $wc.Headers.Add("User-Agent", "Mozilla/5.0 ga-deploy")

    try { $wc.DownloadFile($Url, $OutFile) } finally { $wc.Dispose() }

    if (!(Test-Path $OutFile) -or ((Get-Item $OutFile).Length -lt 1024)) { Die "Download failed: $Url" }

}



function Expand-ZipClean($Zip, $Dest) {

    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }

    New-Item -ItemType Directory -Force -Path $Dest | Out-Null

    Expand-Archive -Path $Zip -DestinationPath $Dest -Force

}



function Copy-DirectoryContents($Src, $Dst) {

    New-Item -ItemType Directory -Force -Path $Dst | Out-Null

    Get-ChildItem -LiteralPath $Src -Force | ForEach-Object {

        Copy-Item -LiteralPath $_.FullName -Destination $Dst -Recurse -Force

    }

}



Say "Install dir: $GaDir"

Say "Mode: $(if ($GlobalMode) { 'GLOBAL=1 / GitHub clone' } else { 'Mainland / VPS zip' })"



if ((Test-Path $GaDir) -and $Force) { Remove-Item -Recurse -Force $GaDir }

New-Item -ItemType Directory -Force -Path $GaDir,$PortableRoot,$Bin,$Cache,$Tools | Out-Null



# uv (GitHub release in GLOBAL mode, user's VPS otherwise)

if (!(Test-Path $UvExe) -or $Force) {

    Download-File $UvUrl $UvZip

    Expand-ZipClean $UvZip $UvExtract

    $foundUv = Get-ChildItem -Path $UvExtract -Recurse -Filter "uv.exe" | Select-Object -First 1

    if (!$foundUv) { Die "uv.exe not found in archive" }

    Copy-Item $foundUv.FullName $UvExe -Force

}

Ok "uv: $(& $UvExe --version)"



# Configure portable Python location. Mirror only in mainland mode.

$env:UV_PYTHON_INSTALL_DIR = Join-Path $PortableRoot "uv-python"

$env:UV_CACHE_DIR = Join-Path $PortableRoot "uv-cache"

if ($GlobalMode) {

    Remove-Item Env:UV_DEFAULT_INDEX -ErrorAction SilentlyContinue

    Remove-Item Env:PIP_INDEX_URL -ErrorAction SilentlyContinue

} else {

    $env:UV_DEFAULT_INDEX = $MainlandIndex

    $env:PIP_INDEX_URL = $MainlandIndex

}

$env:PATH = "$Bin;$env:PATH"




# Workaround: uv creates minor-version symlinks (junctions) in UV_PYTHON_INSTALL_DIR.
# If a previous interrupted install left a plain directory, uv fails with os error 4390.
# Fix: remove any non-junction subdirectory so uv can recreate them cleanly.
$uvPyDir = $env:UV_PYTHON_INSTALL_DIR
if (Test-Path $uvPyDir) {
    Get-ChildItem -LiteralPath $uvPyDir -Directory | ForEach-Object {
        $attr = $_.Attributes
        if (($attr -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
            Say "Removing stale non-junction dir: $($_.Name)"
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
        }
    }
}

Say "Installing Python $PythonVersion via uv"

$ec = Invoke-Native { & $UvExe python install $PythonVersion }

if ($ec -ne 0) { Die "uv python install failed" }

$PythonExe = (& $UvExe python find $PythonVersion).Trim()

if (!(Test-Path $PythonExe)) { Die "uv installed Python but python.exe was not found" }

Ok "Python: $(& $PythonExe --version)"



# PortableGit (GitHub release in GLOBAL mode, user's VPS otherwise). Needed for GLOBAL=1 and useful for user shell.

if (!(Test-Path $GitExe) -or $Force) {

    Download-File $GitUrl $GitExeArchive

    if (Test-Path $GitDir) { Remove-Item -Recurse -Force $GitDir }

    New-Item -ItemType Directory -Force -Path $GitDir | Out-Null

    Say "Extracting PortableGit"

    $ec = Invoke-Native { & $GitExeArchive -y -o"$GitDir" | Out-Null }

    if ($ec -ne 0) { Die "PortableGit extraction failed" }

}

if (!(Test-Path $GitExe)) { Die "git.exe missing: $GitExe" }

Ok "Git: $(& $GitExe --version)"



$PythonDir = Split-Path $PythonExe -Parent

$GitBin = Split-Path $GitExe -Parent

$GitUsrBin = Join-Path $GitDir "usr\bin"

$env:PATH = "$Bin;$PythonDir;$PythonDir\Scripts;$GitBin;$GitUsrBin;$env:PATH"



# Fetch/update GenericAgent source.

if ($GlobalMode) {

    Say "Cloning GenericAgent from GitHub"

    $items = @(Get-ChildItem -LiteralPath $GaDir -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne ".portable" })

    if ($items.Count -gt 0) {

        if (!$Force) { Die "Install dir contains files. Re-run with -Force to replace source while preserving portable tools." }

        $items | Remove-Item -Recurse -Force

    }

    $TmpClone = Join-Path $Cache "ga-clone"

    if (Test-Path $TmpClone) { Remove-Item -Recurse -Force $TmpClone }

    $ec = Invoke-Native { & $GitExe clone --depth 1 $RepoUrl $TmpClone }

    if ($ec -ne 0) { Die "git clone failed" }

    Copy-DirectoryContents $TmpClone $GaDir

    Remove-Item -Recurse -Force $TmpClone

} else {

    Say "Downloading GenericAgent package from VPS"

    Download-File $GaZipUrl $GaZip

    Expand-ZipClean $GaZip $GaExtract

    $SrcDir = Join-Path $GaExtract "GenericAgent"

    if (!(Test-Path $SrcDir)) { $SrcDir = $GaExtract }

    $items = @(Get-ChildItem -LiteralPath $GaDir -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne ".portable" })

    if ($items.Count -gt 0) { $items | Remove-Item -Recurse -Force }

    Copy-DirectoryContents $SrcDir $GaDir

}

Ok "GenericAgent source ready: $GaDir"



# Install basic dependencies and project in editable mode into portable Python.

Say "Installing GenericAgent dependencies via uv pip"

$installArgs = @("pip", "install", "--break-system-packages", "--python", $PythonExe)

if (!$GlobalMode) { $installArgs += @("--index-url", $MainlandIndex) }

$installArgs += $Deps

$ec = Invoke-Native { & $UvExe @installArgs }

if ($ec -ne 0) { Die "dependency install failed" }



if (Test-Path (Join-Path $GaDir "pyproject.toml")) {

    $projectArgs = @("pip", "install", "--break-system-packages", "--python", $PythonExe)

    if (!$GlobalMode) { $projectArgs += @("--index-url", $MainlandIndex) }

    $projectArgs += @("-e", $GaDir)

    $ec = Invoke-Native { & $UvExe @projectArgs }

    if ($ec -ne 0) { Die "editable project install failed" }

}



# Try-install pywebview (optional UI). Failure is non-fatal.

Say "Attempting to install pywebview (optional, failure is OK)"

$webviewArgs = @("pip", "install", "--break-system-packages", "--python", $PythonExe)

if (!$GlobalMode) { $webviewArgs += @("--index-url", $MainlandIndex) }

$webviewArgs += @("pywebview>=4.0")

$ec = Invoke-Native { & $UvExe @webviewArgs 2>&1 | Out-Null }

if ($ec -ne 0) {

    Write-Host "[warn] pywebview install failed. This is optional." -ForegroundColor Yellow

    Write-Host "       On Windows it usually works out of the box." -ForegroundColor Yellow

    Write-Host "       If needed later: uv pip install pywebview" -ForegroundColor Yellow

} else {

    Ok "pywebview installed successfully"

}



# Activation scripts: portable paths are intentionally before system PATH.

if ($GlobalMode) {

@"

@echo off

set "PORTABLE_DEV_ROOT=$PortableRoot"

set "GENERICAGENT_HOME=$GaDir"

set "UV_PYTHON_INSTALL_DIR=$PortableRoot\uv-python"

set "UV_CACHE_DIR=$PortableRoot\uv-cache"

set "PATH=$Bin;$PythonDir;$PythonDir\Scripts;$GitBin;$GitUsrBin;%PATH%"

echo Activated GenericAgent portable env: %GENERICAGENT_HOME%

"@ | Set-Content -Path $EnvCmd -Encoding ASCII



@"

`$env:PORTABLE_DEV_ROOT = "$PortableRoot"

`$env:GENERICAGENT_HOME = "$GaDir"

`$env:UV_PYTHON_INSTALL_DIR = "$PortableRoot\uv-python"

`$env:UV_CACHE_DIR = "$PortableRoot\uv-cache"

`$env:PATH = "$Bin;$PythonDir;$PythonDir\Scripts;$GitBin;$GitUsrBin;`$env:PATH"

Write-Host "Activated GenericAgent portable env: `$env:GENERICAGENT_HOME" -ForegroundColor Green

"@ | Set-Content -Path $EnvPs1 -Encoding UTF8

} else {

@"

@echo off

set "PORTABLE_DEV_ROOT=$PortableRoot"

set "GENERICAGENT_HOME=$GaDir"

set "UV_PYTHON_INSTALL_DIR=$PortableRoot\uv-python"

set "UV_CACHE_DIR=$PortableRoot\uv-cache"

set "UV_DEFAULT_INDEX=$MainlandIndex"

set "PIP_INDEX_URL=$MainlandIndex"

set "PATH=$Bin;$PythonDir;$PythonDir\Scripts;$GitBin;$GitUsrBin;%PATH%"

echo Activated GenericAgent portable env: %GENERICAGENT_HOME%

"@ | Set-Content -Path $EnvCmd -Encoding ASCII



@"

`$env:PORTABLE_DEV_ROOT = "$PortableRoot"

`$env:GENERICAGENT_HOME = "$GaDir"

`$env:UV_PYTHON_INSTALL_DIR = "$PortableRoot\uv-python"

`$env:UV_CACHE_DIR = "$PortableRoot\uv-cache"

`$env:UV_DEFAULT_INDEX = "$MainlandIndex"

`$env:PIP_INDEX_URL = "$MainlandIndex"

`$env:PATH = "$Bin;$PythonDir;$PythonDir\Scripts;$GitBin;$GitUsrBin;`$env:PATH"

Write-Host "Activated GenericAgent portable env: `$env:GENERICAGENT_HOME" -ForegroundColor Green

"@ | Set-Content -Path $EnvPs1 -Encoding UTF8

}



Ok "Verification:"

& $UvExe --version

& $PythonExe --version

& $GitExe --version

& $PythonExe -c "import requests, bs4, bottle; print('deps ok')"

Write-Host ""



# Copy mykey template if mykey.py does not exist (GLOBAL mode only)

$MykeyDst = Join-Path $GaDir "mykey.py"

if ($GlobalMode -and !(Test-Path $MykeyDst)) {

    $MykeyTpl = Join-Path $GaDir "mykey_template_en.py"

    if (Test-Path $MykeyTpl) {

        Copy-Item $MykeyTpl $MykeyDst

        Ok "Copied mykey_template_en.py -> mykey.py"

    }

}



# Final banner

Write-Host ""

if ($GlobalMode) {

    Write-Host @"

╔═══════════════════════════════════════════════╗

║  ✅ GenericAgent installed successfully!       ║

╠═══════════════════════════════════════════════╣

║  📁 Location: $GaDir

║  🔑 Config: edit mykey.py (copied from template)

║  🚀 Launch: ga tui / ga launch / ga hub

╚═══════════════════════════════════════════════╝

"@

} else {

    Write-Host @"

╔═══════════════════════════════════════════════╗

║  [OK] GenericAgent 安装完成！                 ║

╠═══════════════════════════════════════════════╣

║  安装目录: $GaDir

║  配置密钥: ga configure

║  启动: ga tui / ga launch / ga hub

╚═══════════════════════════════════════════════╝

"@

}

Write-Host ""

Write-Host "  Activate env:  cmd.exe → call `"$EnvCmd`"  |  PowerShell → . `"$EnvPs1`""

