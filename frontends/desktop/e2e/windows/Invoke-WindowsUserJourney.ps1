[CmdletBinding()]
param(
    [string]$Repo = "abraxas914/GenericAgent",
    [Parameter(Mandatory = $true)]
    [string]$RunId,
    [string]$ExpectedCommit = "",
    [string]$PackageZip = "",
    [string]$WorkDir = "",
    [ValidateSet("Full", "Smoke", "FailureOnly")]
    [string]$Mode = "Full",
    [switch]$KeepWorkDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

if (-not $WorkDir) {
    $WorkDir = Join-Path $env:TEMP ("ga-desktop-e2e\run-" + $RunId)
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkDir = [System.IO.Path]::GetFullPath($WorkDir)
$DownloadDir = Join-Path $WorkDir "download"
$ExtractDir = Join-Path $WorkDir "app"
$ReportDir = Join-Path $WorkDir "report"
$ScreensDir = Join-Path $ReportDir "screenshots"
$ReportPath = Join-Path $ReportDir "e2e-report.json"
$RunSucceeded = $false
$PortWasFreeAtStart = $false
$UserHome = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
$SettingsPath = Join-Path $UserHome ".ga_desktop_settings.json"
$SettingsExisted = Test-Path -LiteralPath $SettingsPath
[byte[]]$SettingsBackupBytes = @()
$SettingsAttributes = $null
if ($SettingsExisted) {
    $SettingsBackupBytes = [System.IO.File]::ReadAllBytes($SettingsPath)
    $SettingsAttributes = [System.IO.File]::GetAttributes($SettingsPath)
}

$Report = [ordered]@{
    repo = $Repo
    runId = $RunId
    expectedCommit = $ExpectedCommit
    mode = $Mode
    package = [ordered]@{}
    environment = [ordered]@{}
    checks = [ordered]@{}
    screenshots = @()
    manualChecklist = [ordered]@{
        windowsTitlebarVisible = "manual"
        exactlyThreeWindowButtons = "manual"
        titlebarBlankAreaDrags = "manual"
        buttonAreaDoesNotDrag = "manual"
        minimizeWorks = "manual"
        maximizeRestoreWorks = "manual"
        closeHidesToTray = "manual"
        sidebarNavHasNoBlankRow = "manual"
        nativeDirectoryPicker = "manual"
        shortcutSelfHealsAfterMove = "manual"
        loadingFallbackAndMainRender = "manual"
    }
    failures = @()
    startedAt = (Get-Date).ToUniversalTime().ToString("o")
}

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
}

function Add-Failure([string]$Message) {
    $script:Report.failures += $Message
}

function Save-Report {
    $script:Report.completedAt = (Get-Date).ToUniversalTime().ToString("o")
    $json = $script:Report | ConvertTo-Json -Depth 12
    [System.IO.Directory]::CreateDirectory($ReportDir) | Out-Null
    [System.IO.File]::WriteAllText($ReportPath, $json, [System.Text.UTF8Encoding]::new($false))
}

function Fail([string]$Message) {
    Add-Failure $Message
    Save-Report
    throw $Message
}

function Ensure-Dir([string]$Path) {
    [System.IO.Directory]::CreateDirectory($Path) | Out-Null
}

function Test-Command([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    return $null -ne $cmd
}

function Normalize-Commit([string]$Commit) {
    return ($Commit -replace "\s", "").ToLowerInvariant()
}

function Test-CommitMatches([string]$Actual, [string]$Expected) {
    if (-not $Expected) { return $true }
    $actualNorm = Normalize-Commit $Actual
    $expectedNorm = Normalize-Commit $Expected
    return $actualNorm.StartsWith($expectedNorm) -or $expectedNorm.StartsWith($actualNorm)
}

function Get-RunMetadata {
    if (-not (Test-Command "gh")) {
        Fail "GitHub CLI 'gh' is required when -PackageZip is not enough to skip run metadata."
    }
    $json = & gh run view $RunId --repo $Repo --json headSha,status,conclusion,event,name 2>&1
    if ($LASTEXITCODE -ne 0) {
        Fail "gh run view failed: $json"
    }
    $meta = ($json | Out-String) | ConvertFrom-Json
    $script:Report.run = $meta
    if ($ExpectedCommit -and -not (Test-CommitMatches $meta.headSha $ExpectedCommit)) {
        Fail "Run headSha $($meta.headSha) does not match expected commit $ExpectedCommit"
    }
    return $meta
}

function Resolve-PackageZip {
    Ensure-Dir $DownloadDir
    if ($PackageZip) {
        $zipPath = [System.IO.Path]::GetFullPath($PackageZip)
        if (-not (Test-Path -LiteralPath $zipPath)) {
            Fail "Package zip not found: $zipPath"
        }
        return $zipPath
    }

    if (-not (Test-Command "gh")) {
        Fail "GitHub CLI 'gh' is required to download artifacts."
    }

    Write-Step "Download GitHub Actions artifact"
    $downloadOutput = & gh run download $RunId --repo $Repo --dir $DownloadDir 2>&1
    if ($LASTEXITCODE -ne 0) {
        Fail "gh run download failed: $downloadOutput"
    }

    $zips = @(Get-ChildItem -LiteralPath $DownloadDir -Recurse -Filter "GenericAgent-Desktop-Windows-Portable.zip")
    if ($zips.Count -ne 1) {
        Fail "Expected exactly one GenericAgent-Desktop-Windows-Portable.zip under $DownloadDir, found $($zips.Count)"
    }
    return $zips[0].FullName
}

function Test-Sha256([string]$ZipPath) {
    Write-Step "Verify SHA-256"
    $hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaFile = $ZipPath + ".sha256"
    if (-not (Test-Path -LiteralPath $shaFile)) {
        $matches = @(Get-ChildItem -LiteralPath (Split-Path -Parent $ZipPath) -Recurse -File | Where-Object {
            $_.Name -like "*.sha256" -or $_.Name -like "SHA256SUMS*.txt"
        })
        if ($matches.Count -eq 1) {
            $shaFile = $matches[0].FullName
        }
    }
    if (Test-Path -LiteralPath $shaFile) {
        $expectedText = [System.IO.File]::ReadAllText($shaFile)
        $expectedHash = ([regex]::Match($expectedText, "[A-Fa-f0-9]{64}")).Value.ToLowerInvariant()
        if (-not $expectedHash) {
            Fail "Could not parse SHA-256 from $shaFile"
        }
        if ($hash -ne $expectedHash) {
            Fail "SHA-256 mismatch. actual=$hash expected=$expectedHash"
        }
        $script:Report.package.sha256File = $shaFile
        $script:Report.package.expectedSha256 = $expectedHash
    } else {
        Fail "SHA-256 sidecar not found next to $ZipPath"
    }
    $script:Report.package.sha256 = $hash
}

function Expand-Package([string]$ZipPath) {
    Write-Step "Extract package"
    if (Test-Path -LiteralPath $ExtractDir) {
        Remove-Item -LiteralPath $ExtractDir -Recurse -Force
    }
    Ensure-Dir $ExtractDir
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExtractDir -Force

    $packageRoot = Join-Path $ExtractDir "GenericAgent-Desktop-Windows-Portable"
    if (-not (Test-Path -LiteralPath $packageRoot)) {
        $dirs = @(Get-ChildItem -LiteralPath $ExtractDir -Directory)
        if ($dirs.Count -eq 1) {
            $packageRoot = $dirs[0].FullName
        }
    }
    if (-not (Test-Path -LiteralPath $packageRoot)) {
        Fail "Could not find extracted package root under $ExtractDir"
    }
    return [System.IO.Path]::GetFullPath($packageRoot)
}

function Assert-PackageShape([string]$PackageRoot) {
    Write-Step "Validate package structure"
    $required = @(
        "GenericAgent.exe",
        "runtime\install_windows.ps1",
        "runtime\wheels",
        "runtime\python",
        "runtime\app\frontends\desktop_bridge.py"
    )
    foreach ($rel in $required) {
        $path = Join-Path $PackageRoot $rel
        if (-not (Test-Path -LiteralPath $path)) {
            Fail "Package is missing required path: $rel"
        }
    }
    $script:Report.package.root = $PackageRoot
    $script:Report.package.exe = Join-Path $PackageRoot "GenericAgent.exe"
    $script:Report.package.form = "windows-portable-zip"
}

function Get-WindowsEnvironment {
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $arch = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } else { [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() }
    return [ordered]@{
        caption = $os.Caption
        version = $os.Version
        buildNumber = $os.BuildNumber
        architecture = $arch
        cpu = $cpu.Name
        userInteractive = [Environment]::UserInteractive
        webView2Installed = Test-WebView2Installed
    }
}

function Test-WebView2Installed {
    $keys = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    foreach ($key in $keys) {
        if (Test-Path $key) { return $true }
    }
    return $false
}

function Get-PortState {
    try {
        $connections = @(Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort 14168 -ErrorAction SilentlyContinue)
        return @($connections | Select-Object LocalAddress, LocalPort, State, OwningProcess)
    } catch {
        return @()
    }
}

function Get-GaProcesses {
    return @(Get-Process | Where-Object {
        $_.ProcessName -like "GenericAgent*" -or $_.ProcessName -like "ga-desktop*" -or $_.ProcessName -like "python*"
    } | Select-Object ProcessName, Id, Path)
}

function Stop-ProcessTreeSafe([int]$ProcessId) {
    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    } catch {}
}

function Capture-Screenshot([string]$Name) {
    Ensure-Dir $ScreensDir
    $path = Join-Path $ScreensDir $Name
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bitmap = [System.Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose()
        $bitmap.Dispose()
        $script:Report.screenshots += $path
        return $path
    } catch {
        Add-Failure "Screenshot failed for ${Name}: $($_.Exception.Message)"
        return $null
    }
}

function Wait-ForBootstrapPhase(
    [string]$ReportDirectory,
    [string]$Phase,
    [int]$TimeoutSeconds,
    [int]$AfterSequence = 0
) {
    $latest = Join-Path $ReportDirectory "bootstrap-latest.json"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $latest) {
            try {
                $snapshot = [System.IO.File]::ReadAllText($latest) | ConvertFrom-Json
                if ([int]$snapshot.seq -le $AfterSequence) {
                    Start-Sleep -Milliseconds 500
                    continue
                }
                if ($snapshot.phase -eq $Phase) {
                    return $snapshot
                }
                if ($Phase -ne "failed" -and $snapshot.phase -eq "failed") {
                    return $snapshot
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Wait-ForBootstrapAnyPhase([string]$ReportDirectory, [string[]]$Phases, [int]$TimeoutSeconds) {
    $latest = Join-Path $ReportDirectory "bootstrap-latest.json"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $latest) {
            try {
                $snapshot = [System.IO.File]::ReadAllText($latest) | ConvertFrom-Json
                if ($Phases -contains [string]$snapshot.phase) {
                    return $snapshot
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Wait-ForBridgeIdentity([string]$ExpectedRoot, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $identity = Invoke-RestMethod -Uri "http://127.0.0.1:14168/services/identity" -TimeoutSec 2
            if ($identity.ga_root) {
                $reported = [System.IO.Path]::GetFullPath([string]$identity.ga_root).TrimEnd('\')
                $expected = [System.IO.Path]::GetFullPath($ExpectedRoot).TrimEnd('\')
                if ($reported.Equals($expected, [System.StringComparison]::OrdinalIgnoreCase)) {
                    return $identity
                }
            }
        } catch {}
        Start-Sleep -Milliseconds 700
    }
    return $null
}

function Start-GenericAgent([string]$PackageRoot, [string]$Scenario) {
    $exe = Join-Path $PackageRoot "GenericAgent.exe"
    $scenarioReportDir = Join-Path $ReportDir $Scenario
    Ensure-Dir $scenarioReportDir
    $env:GA_DESKTOP_E2E_REPORT_DIR = $scenarioReportDir
    try {
        return Start-Process -FilePath $exe -WorkingDirectory $PackageRoot -PassThru
    } finally {
        Remove-Item Env:\GA_DESKTOP_E2E_REPORT_DIR -ErrorAction SilentlyContinue
    }
}

function Stop-GenericAgent {
    foreach ($proc in @(Get-Process GenericAgent -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($proc in @(Get-Process ga-desktop -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

function Stop-BridgeOnPort {
    foreach ($conn in @(Get-PortState)) {
        if ($conn.OwningProcess) {
            try {
                $proc = Get-Process -Id $conn.OwningProcess -ErrorAction Stop
                if ($proc.ProcessName -like "python*" -or $proc.ProcessName -like "GenericAgent*" -or $proc.ProcessName -like "ga-desktop*") {
                    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }
    }
}

function Invoke-FreshLaunch([string]$PackageRoot) {
    Write-Step "Fresh launch and first-run prepare"
    $marker = Join-Path $PackageRoot "runtime\.prepared"
    if (Test-Path -LiteralPath $marker) {
        Fail "Fresh package already has runtime\\.prepared before launch"
    }

    $proc = Start-GenericAgent $PackageRoot "fresh"
    $script:Report.checks.freshProcessId = $proc.Id
    Start-Sleep -Seconds 2
    Capture-Screenshot "loading-first.png" | Out-Null
    $prepSnapshot = Wait-ForBootstrapAnyPhase (Join-Path $ReportDir "fresh") @("preparing", "ready", "failed") 30
    if ($prepSnapshot -and $prepSnapshot.phase -eq "preparing") {
        Capture-Screenshot "preparing.png" | Out-Null
    } else {
        $prepPhase = if ($prepSnapshot) { [string]$prepSnapshot.phase } else { "unavailable" }
        $script:Report.checks.preparingScreenshot = "not captured; phase was $prepPhase"
    }

    $snapshot = Wait-ForBootstrapPhase (Join-Path $ReportDir "fresh") "ready" 240
    if (-not $snapshot -or $snapshot.phase -ne "ready") {
        Capture-Screenshot "fresh-failed.png" | Out-Null
        Fail "Fresh launch did not reach bootstrap ready"
    }

    if (-not (Test-Path -LiteralPath $marker)) {
        Fail "Fresh launch reached ready but runtime\\.prepared was not created"
    }
    $identity = Wait-ForBridgeIdentity (Join-Path $PackageRoot "runtime\app") 30
    if (-not $identity) {
        Fail "Bridge identity did not match extracted runtime app"
    }
    Capture-Screenshot "main-ready.png" | Out-Null
    $script:Report.checks.freshReady = $true
    $script:Report.checks.bridgeIdentity = $identity
}

function Start-ForeignPortListener {
    Write-Step "Start unknown foreign listener on 127.0.0.1:14168"
    $ready = Join-Path $WorkDir "foreign-listener.ready"
    Remove-Item -LiteralPath $ready -Force -ErrorAction SilentlyContinue
    $fixture = Join-Path $ScriptRoot "fixtures\foreign-port-listener.ps1"
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $fixture,
        "-Port", "14168",
        "-ReadyFile", $ready
    ) -WindowStyle Hidden -PassThru
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        if ((Test-Path -LiteralPath $ready) -and (Get-PortState).Count -gt 0) {
            return $proc
        }
        Start-Sleep -Milliseconds 250
    }
    Stop-ProcessTreeSafe $proc.Id
    Fail "Foreign listener did not bind 127.0.0.1:14168"
}

function Invoke-SetupRetry(
    [System.Diagnostics.Process]$AppProcess,
    [int]$TimeoutSeconds,
    [int]$AfterSequence
) {
    Add-Type -AssemblyName System.Windows.Forms
    $sig = @"
using System;
using System.Runtime.InteropServices;
public static class Win32Focus {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
    Add-Type -TypeDefinition $sig -ErrorAction SilentlyContinue
    try {
        $AppProcess.Refresh()
        if ($AppProcess.MainWindowHandle -ne [IntPtr]::Zero) {
            [Win32Focus]::ShowWindow($AppProcess.MainWindowHandle, 9) | Out-Null
            [Win32Focus]::SetForegroundWindow($AppProcess.MainWindowHandle) | Out-Null
            Start-Sleep -Milliseconds 500
            [System.Windows.Forms.SendKeys]::SendWait("{TAB}{TAB}{ENTER}")
        }
    } catch {
        Add-Failure "Automatic setup retry keypress failed: $($_.Exception.Message)"
    }

    $snapshot = Wait-ForBootstrapPhase `
        (Join-Path $ReportDir "port-conflict") "ready" $TimeoutSeconds $AfterSequence
    if ($snapshot -and $snapshot.phase -eq "ready") {
        $script:Report.checks.setupRetry = "automatic"
        return $true
    }

    Write-Host ""
    Write-Host "Manual action required: click 'Retry startup' in the setup window."
    $snapshot = Wait-ForBootstrapPhase `
        (Join-Path $ReportDir "port-conflict") "ready" 180 $AfterSequence
    if ($snapshot -and $snapshot.phase -eq "ready") {
        $script:Report.checks.setupRetry = "manual"
        return $true
    }
    return $false
}

function Invoke-PortConflictScenario([string]$PackageRoot) {
    Write-Step "Port conflict recovery scenario"
    Stop-GenericAgent
    Stop-BridgeOnPort
    Start-Sleep -Seconds 2

    $listener = Start-ForeignPortListener
    $script:Report.checks.foreignListenerPid = $listener.Id
    $appProc = Start-GenericAgent $PackageRoot "port-conflict"
    Start-Sleep -Seconds 2

    $failed = Wait-ForBootstrapPhase (Join-Path $ReportDir "port-conflict") "failed" 80
    if (-not $failed -or $failed.phase -ne "failed") {
        Stop-ProcessTreeSafe $listener.Id
        Fail "Port conflict scenario did not reach failed phase"
    }
    if ($failed.failure.code -ne "port_conflict") {
        Stop-ProcessTreeSafe $listener.Id
        Fail "Expected port_conflict, got $($failed.failure.code)"
    }
    try {
        Get-Process -Id $listener.Id -ErrorAction Stop | Out-Null
        $script:Report.checks.foreignListenerSurvived = $true
    } catch {
        Fail "Foreign listener was not alive after port_conflict"
    }
    Capture-Screenshot "setup-failure.png" | Out-Null

    Stop-ProcessTreeSafe $listener.Id
    Start-Sleep -Seconds 2
    if (-not (Invoke-SetupRetry $appProc 40 ([int]$failed.seq))) {
        Fail "Setup retry did not reach ready after releasing port"
    }
    Capture-Screenshot "setup-retry-ready.png" | Out-Null
    $script:Report.checks.portConflictRecovery = $true
}

function Invoke-ProductionContractJourney(
    [string]$PackageRoot,
    [string]$ZipPath
) {
    Write-Step "Run production package chat, data, relocation, and fallback journey"
    if (-not $ExpectedCommit) {
        Fail "Full mode requires -ExpectedCommit for the production build identity assertion"
    }
    Stop-GenericAgent
    Stop-BridgeOnPort
    Start-Sleep -Seconds 2

    # The package itself must be movable while the journey is running.  Running the driver
    # with runtime\python\python.exe would keep that executable open and make Windows reject
    # the relocation, so copy the already-prepared embedded interpreter outside the package.
    $driverPythonRoot = Join-Path $WorkDir "production-contract-python"
    if (Test-Path -LiteralPath $driverPythonRoot) {
        Remove-Item -LiteralPath $driverPythonRoot -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $PackageRoot "runtime\python") `
        -Destination $driverPythonRoot -Recurse -Force
    $python = Join-Path $driverPythonRoot "python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        Fail "Could not create an out-of-package Python for the relocation journey"
    }
    $driver = [System.IO.Path]::GetFullPath((Join-Path $ScriptRoot "..\package\real_package_journey.py"))
    $contractReport = Join-Path $ReportDir "production-contract"
    $contractWork = Join-Path $WorkDir "production-contract-work"
    $relocated = Join-Path $ExtractDir "relocated\含 空格\GenericAgent 包"
    & $python $driver `
        --platform windows `
        --artifact $ZipPath `
        --expected-commit $ExpectedCommit `
        --package-root $PackageRoot `
        --application-relative "GenericAgent.exe" `
        --runtime-relative "runtime" `
        --relocated-root $relocated `
        --report-dir $contractReport `
        --work-dir $contractWork `
        --allow-user-settings-mutation `
        --screenshots-optional
    if ($LASTEXITCODE -ne 0) {
        Fail "Production package contract journey failed; see $contractReport"
    }
    $script:Report.checks.productionContract = [System.IO.File]::ReadAllText(
        (Join-Path $contractReport "real-package-report.json")
    ) | ConvertFrom-Json
}

try {
    Ensure-Dir $WorkDir
    Ensure-Dir $ReportDir
    Ensure-Dir $ScreensDir
    $Report.environment = Get-WindowsEnvironment

    if (-not $PackageZip) {
        Write-Step "Read GitHub Actions run metadata"
        Get-RunMetadata | Out-Null
    } elseif ($ExpectedCommit) {
        $Report.run = [ordered]@{ headSha = $ExpectedCommit; source = "local-package" }
    }

    $zip = Resolve-PackageZip
    $Report.package.zip = $zip
    Test-Sha256 $zip
    $packageRoot = Expand-Package $zip
    Assert-PackageShape $packageRoot
    $Report.environment.initialPortState = @(Get-PortState)
    $Report.environment.initialProcesses = @(Get-GaProcesses)
    if ($Report.environment.initialPortState.Count -gt 0) {
        Fail "127.0.0.1:14168 was already occupied before the package journey"
    }
    $script:PortWasFreeAtStart = $true

    if ($Mode -eq "Smoke" -or $Mode -eq "Full") {
        Invoke-FreshLaunch $packageRoot
    }
    if ($Mode -eq "FailureOnly" -or $Mode -eq "Full") {
        Invoke-PortConflictScenario $packageRoot
    }
    if ($Mode -eq "Full") {
        Invoke-ProductionContractJourney $packageRoot $zip
    }

    Stop-GenericAgent
    Stop-BridgeOnPort
    Start-Sleep -Seconds 2
    $Report.environment.finalPortState = @(Get-PortState)
    $Report.environment.finalProcesses = @(Get-GaProcesses)
    if ($Report.environment.finalPortState.Count -gt 0) {
        Fail "Package journey left a listener on 127.0.0.1:14168"
    }
    $Report.success = $true
    $script:RunSucceeded = $true
    Save-Report
    Write-Host ""
    Write-Host "E2E report: $ReportPath"
} catch {
    $Report.success = $false
    Add-Failure $_.Exception.Message
    $Report.environment.finalPortState = @(Get-PortState)
    $Report.environment.finalProcesses = @(Get-GaProcesses)
    Save-Report
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($script:PortWasFreeAtStart) {
        Stop-GenericAgent
        Stop-BridgeOnPort
    }
    if ($SettingsExisted) {
        [System.IO.File]::WriteAllBytes($SettingsPath, $SettingsBackupBytes)
        if ($null -ne $SettingsAttributes) {
            [System.IO.File]::SetAttributes($SettingsPath, $SettingsAttributes)
        }
    } else {
        Remove-Item -LiteralPath $SettingsPath -Force -ErrorAction SilentlyContinue
    }
    $script:Report.checks.settingsRestored = if ($SettingsExisted) {
        [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($SettingsPath)) -eq `
            [Convert]::ToBase64String($SettingsBackupBytes)
    } else {
        -not (Test-Path -LiteralPath $SettingsPath)
    }
    Save-Report
    if ($script:RunSucceeded -and -not $KeepWorkDir) {
        Remove-Item -LiteralPath $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $DownloadDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Report kept at: $ReportDir"
    } else {
        Write-Host "WorkDir kept for diagnostics: $WorkDir"
    }
}
