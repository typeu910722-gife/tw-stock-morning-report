@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 請先執行 run_report.bat 一次。
    pause
    exit /b 1
)
schtasks /Create /TN "台股前一交易日晨報V3" /TR "\"%CD%\scheduled_run.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 07:40 /F
echo 已建立週一至週五 07:40 排程。
pause
