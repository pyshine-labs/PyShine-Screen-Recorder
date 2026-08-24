@echo off
REM Build the native C++ recorder DLL using MSVC + CMake
REM Usage: build.bat

setlocal

REM Find Visual Studio Build Tools
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" set "VSWHERE=%ProgramFiles%\Microsoft Visual Studio\Installer\vswhere.exe"

for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSINSTALL=%%i"

if not defined VSINSTALL (
    echo ERROR: Visual Studio Build Tools not found
    exit /b 1
)

call "%VSINSTALL%\VC\Auxiliary\Build\vcvars64.bat"

REM Build with CMake
cd /d "%~dp0\.."
cmake -B native\build -S native -G "Ninja" -DCMAKE_BUILD_TYPE=Release 2>nul
if errorlevel 1 (
    cmake -B native\build -S native -DCMAKE_BUILD_TYPE=Release
)
cmake --build native\build --config Release

if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo.
echo BUILD SUCCESSFUL: bin\recorder.dll
endlocal
