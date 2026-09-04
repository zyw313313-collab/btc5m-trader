@echo off
setlocal
cd /d "%~dp0"
python -c "import aiohttp" >nul 2>&1
if errorlevel 1 (
    python -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo Failed to install runtime dependencies.
        pause
        exit /b 1
    )
)
python "%~dp0start_btc5m.py"
endlocal
