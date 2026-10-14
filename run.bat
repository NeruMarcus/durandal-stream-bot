@echo off
chcp 65001 >nul
cd /d "%~dp0"

set TARGET=main.py
if /i "%~1"=="auth" set TARGET=auth_twitch.py
if /i "%~1"=="check" set TARGET=check.py
if /i "%~1"=="overlay" set TARGET=overlay_server.py

echo.
echo   =====================================================
echo    DURANDAL // STREAM BOT [%TARGET%]
echo    OVERLAY : http://127.0.0.1:9733/overlay  (845x230)
echo    AUTH    : run.bat auth   -^> browser auto-opens
echo    CHECK   : run.bat check  -^> sandbox self-test
echo    OVERLAY : run.bat overlay -^> design preview only (no bot)
echo   =====================================================
echo.

set PYEXE=%~dp0venv\Scripts\python.exe
if exist "%PYEXE%" goto :run_venv

where python >nul 2>nul
if errorlevel 1 goto :nopython
echo   [WARN] venv not found, using system python.
python "%TARGET%"
goto :end

:nopython
echo   [ERROR] python not found in PATH.
goto :end

:run_venv
"%PYEXE%" "%TARGET%"
if not "%TARGET%"=="main.py" goto end
echo.
echo   [WARN] bot exited, restart in 5s... (Ctrl+C to stop)
timeout /t 5 /nobreak >nul
goto run_venv

:end
pause
