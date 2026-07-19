@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo 台股前一交易日晨報 V3
echo ==========================================

if not exist ".venv\Scripts\python.exe" (
    echo [首次執行] 建立 Python 環境...
    py -m venv .venv
    if errorlevel 1 (
        echo 找不到 Python。請先安裝 Python 3.11 以上版本。
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
python main.py
echo.
pause
