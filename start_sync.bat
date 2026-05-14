@echo off
:: start_sync.bat — 启动 Telegram 同步
set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo ========================================
echo  启动 Telegram 视频同步
echo ========================================
python tg_sync.py
pause
