# Build native C++ recorder DLL using MSVC + CMake
$ErrorActionPreference = "Stop"

# Find Visual Studio Build Tools
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    $vswhere = "$env:ProgramFiles\Microsoft Visual Studio\Installer\vswhere.exe"
}
if (-not (Test-Path $vswhere)) {
    Write-Host "ERROR: vswhere not found" -ForegroundColor Red
    exit 1
}

$vsInstall = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsInstall) {
    Write-Host "ERROR: Visual Studio Build Tools not found" -ForegroundColor Red
    exit 1
}
Write-Host "Found VS: $vsInstall" -ForegroundColor Green

# Load VS DevShell environment (PowerShell-native, no cmd /c)
$devShellDll = "$vsInstall\Common7\Tools\Microsoft.VisualStudio.DevShell.dll"
if (Test-Path $devShellDll) {
    Import-Module $devShellDll
    Enter-VsDevShell -VsInstallPath $vsInstall -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
    Write-Host "MSVC environment loaded via VsDevShell" -ForegroundColor Green
} else {
    Write-Host "ERROR: VsDevShell.dll not found" -ForegroundColor Red
    exit 1
}

# Build with CMake
Set-Location "$PSScriptRoot\.."
Write-Host "Configuring CMake..." -ForegroundColor Cyan
cmake -B native\build -S native -DCMAKE_BUILD_TYPE=Release -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded 2>&1 | Write-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "CMake configure failed" -ForegroundColor Red
    exit 1
}

Write-Host "Building..." -ForegroundColor Cyan
cmake --build native\build --config Release 2>&1 | Write-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "BUILD FAILED" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "BUILD SUCCESSFUL: bin\Release\recorder.dll" -ForegroundColor Green

# Verify static CRT linkage
Write-Host ""
Write-Host "Verifying DLL dependencies..." -ForegroundColor Cyan
$dumpbin = Get-ChildItem "$vsInstall" -Recurse -Filter "dumpbin.exe" | Where-Object { $_.FullName -notmatch "x86" } | Select-Object -First 1
if ($dumpbin) {
    $deps = & $dumpbin.FullName /dependents "bin\Release\recorder.dll" 2>&1
    $dllDeps = @($deps | Select-String "\.dll" | ForEach-Object { $_.Matches.Value })
    Write-Host "Dependencies: $([string]::Join(', ', $dllDeps))"
    if ($dllDeps -contains "VCRUNTIME140.dll" -or $dllDeps -contains "MSVCP140.dll") {
        Write-Host "WARNING: Still depends on CRT DLLs" -ForegroundColor Yellow
    } else {
        Write-Host "OK: No external CRT dependencies" -ForegroundColor Green
    }
}
