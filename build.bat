@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  SoundDeck — Build Script
echo ============================================================
echo.

:: --- Locate real python.exe (works around Microsoft Store stubs) ------------
set "PYTHON="
for /f "delims=" %%i in ('where pip 2^>nul') do (
    if not defined PYTHON for %%j in ("%%~dpi..\python.exe") do (
        if exist "%%~fj" set "PYTHON=%%~fj"
    )
)
if not defined PYTHON for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYTHON=%%i"
if not defined PYTHON (
    echo ERROR: Could not locate python.exe.
    echo The Microsoft Store python alias is likely shadowing your real install.
    echo Disable it: Settings ^> Apps ^> Advanced app settings ^> App execution aliases.
    if not defined SKIP_PAUSE pause
    exit /b 1
)
echo Using Python: %PYTHON%

:: --- Install dependencies ---------------------------------------------------
echo [1/3] Installing Python dependencies...
"%PYTHON%" -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% neq 0 (
    echo ERROR: pip install failed. Make sure Python 3.10+ is on your PATH.
    if not defined SKIP_PAUSE pause
    exit /b 1
)

:: --- Generate icon ----------------------------------------------------------
echo [2/3] Generating app icon...
"%PYTHON%" make_icon.py
if %ERRORLEVEL% neq 0 (
    echo WARNING: Icon generation failed -- will use default icon.
    set ICON_ARG=
) else (
    set ICON_ARG=--icon=sounddeck.ico
)

:: --- PyInstaller ------------------------------------------------------------
echo [3/3] Building executable...
"%PYTHON%" -m PyInstaller --onedir --windowed --name SoundDeck %ICON_ARG% --hidden-import=pycaw --hidden-import=pycaw.pycaw --hidden-import=pycaw.api.mmdeviceapi --hidden-import=pycaw.constants --hidden-import=comtypes --hidden-import=comtypes.client --hidden-import=pystray._win32 --hidden-import=PIL --collect-all=pycaw --collect-all=comtypes main.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: PyInstaller build failed. See output above.
    if not defined SKIP_PAUSE pause
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete!
echo  Executable: dist\SoundDeck\SoundDeck.exe
echo ============================================================
echo.
echo  Run dist\SoundDeck\SoundDeck.exe directly.
echo  To move it, copy the entire dist\SoundDeck\ folder.
echo.
if not defined SKIP_PAUSE pause