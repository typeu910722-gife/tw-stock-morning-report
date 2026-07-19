@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
python main.py >> "logs\scheduled_console.log" 2>&1
