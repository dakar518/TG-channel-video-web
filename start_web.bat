@echo off
:: start_web.bat — 启动 Web 服务
set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo ========================================
echo  启动 ReelVault 网站服务
echo  访问地址: http://localhost:8000
echo  按 Ctrl+C 停止服务
echo ========================================
python -m uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
pause
