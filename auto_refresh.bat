@echo off
:: auto_refresh.bat — 每晚定时执行：下载新视频 → 生成缩略图 → 重启网站
:: 放到项目目录，用任务计划程序定时调用

set PROJECT_DIR=%~dp0
set LOG_FILE=%PROJECT_DIR%refresh.log
set PYTHON=python

echo ====================================== >> "%LOG_FILE%"
echo 开始刷新: %date% %time% >> "%LOG_FILE%"
echo ====================================== >> "%LOG_FILE%"

cd /d "%PROJECT_DIR%"

:: ── 第一步：停止旧的 Web 服务 ─────────────────────────────────────────────
echo [1/4] 停止旧 Web 服务... >> "%LOG_FILE%"
taskkill /F /IM python.exe /FI "WINDOWTITLE eq uvicorn*" >nul 2>&1
:: 等待进程退出
timeout /t 3 /nobreak >nul

:: ── 第二步：同步 Telegram 视频 ───────────────────────────────────────────
echo [2/4] 开始同步 Telegram 视频... >> "%LOG_FILE%"
%PYTHON% tg_sync.py >> "%LOG_FILE%" 2>&1

:: ── 第三步：重启 Web 服务 ────────────────────────────────────────────────
echo [3/4] 重启 Web 服务... >> "%LOG_FILE%"
start "uvicorn" /B %PYTHON% -m uvicorn api_server:app --host 0.0.0.0 --port 8000 >> "%LOG_FILE%" 2>&1

:: ── 第四步：完成 ─────────────────────────────────────────────────────────
echo [4/4] 全部完成: %date% %time% >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
