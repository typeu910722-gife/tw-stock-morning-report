@echo off
cd /d "%~dp0"
chcp 65001 >nul

echo Starting Taiwan Stock Morning Report...
echo.

where py >nul 2>&1
if not errorlevel 1 (
    py -3 main.py
    goto end
)

where python >nul 2>&1
if not errorlevel 1 (
    python main.py
    goto end
)

echo Python was not found.
echo Please install Python 3 and enable Add Python to PATH.

:end
echo.
pause