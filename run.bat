@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   =====================================================
echo    DURANDAL // STREAM BOT
echo    OVERLAY : http://127.0.0.1:9733/overlay
echo    OBS     : 845x230 Browser Source
echo   =====================================================
echo.

"%~dp0venv\Scripts\python.exe" main.py
pause
