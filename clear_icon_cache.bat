@echo off
echo === Clearing Windows Icon Cache ===
echo.

echo Step 1: Stopping explorer.exe...
taskkill /F /IM explorer.exe >nul 2>&1

echo Step 2: Waiting for handles to release...
timeout /t 2 /nobreak >nul

echo Step 3: Deleting icon cache files...

REM Main icon cache
del /F /Q /A "%LOCALAPPDATA%\IconCache.db" 2>nul
if exist "%LOCALAPPDATA%\IconCache.db" (echo   FAILED: IconCache.db still locked) else (echo   Deleted: IconCache.db)

REM Explorer icon cache files
del /F /Q /A "%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.db" 2>nul
del /F /Q /A "%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.idx" 2>nul
del /F /Q /A "%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db" 2>nul
del /F /Q /A "%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.idx" 2>nul
echo   Cleared Explorer cache files

REM Also clear the WinX cache
del /F /Q /A "%LOCALAPPDATA%\Microsoft\Windows\WinX\*" 2>nul

echo Step 4: Refreshing icon cache...
ie4uinit.exe -show >nul 2>&1

echo Step 5: Restarting explorer.exe...
start explorer.exe

echo.
echo === Icon cache cleared! ===
echo.
echo If the EXE icon still does not show correctly:
echo   1. Reboot the computer (some cache entries require a full restart)
echo   2. Or copy the EXE to a new filename to bypass the cache entirely
echo.
pause
