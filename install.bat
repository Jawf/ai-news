@echo off
cd /d "%~dp0"

echo ============================================
echo  AI News Job Manager - Install
echo ============================================
echo.

uv --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv not found. Install it first:
    echo   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

echo [1/3] Syncing Python dependencies...
uv sync
if errorlevel 1 (
    echo [ERROR] uv sync failed.
    pause
    exit /b 1
)

echo.
echo [2/3] Checking Claude CLI...
claude --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] claude not found. Install it:
    echo   npm install -g @anthropic-ai/claude-code
) else (
    echo [OK] Claude CLI is ready.
)

echo.
echo [3/3] Checking nanobot...
nanobot --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] nanobot not found. Please install and configure it.
) else (
    echo [OK] nanobot is ready.
)

echo.
echo ============================================
echo  Done. Run start.bat to launch the app.
echo ============================================
pause
