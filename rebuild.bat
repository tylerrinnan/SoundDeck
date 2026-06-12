@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Closing running SoundDeck...
taskkill /F /IM SoundDeck.exe >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Closed.
    timeout /t 1 /nobreak >nul
) else (
    echo Not running.
)
echo.

echo [2/4] Deleting dist folder...
if exist dist (
    rmdir /s /q dist
    if exist dist (
        echo ERROR: Could not delete dist. A file is locked.
        pause & exit /b 1
    )
    echo Done.
) else (
    echo dist folder not found, skipping.
)
echo.

echo [3/4] Building...
set SKIP_PAUSE=1
call "%~dp0build.bat"
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

echo [4/4] Launching SoundDeck...
if exist "%~dp0dist\SoundDeck\SoundDeck.exe" (
    start "" "%~dp0dist\SoundDeck\SoundDeck.exe"
    echo Launched.
) else (
    echo ERROR: Build artifact not found.
    exit /b 1
)
