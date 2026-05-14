@echo off
:: add_scheduled_tasks.bat — 添加 Windows 定时任务
:: 需要以管理员身份运行

set PROJECT_DIR=%~dp0
:: 去掉末尾反斜杠
if "%PROJECT_DIR:~-1%"=="\" set PROJECT_DIR=%PROJECT_DIR:~0,-1%

echo ========================================
echo  添加 Windows 定时任务
echo  需要管理员权限
echo ========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if errorlevel 1 (
    echo ❌ 请右键此文件，选择"以管理员身份运行"
    pause
    exit /b 1
)

:: 删除旧任务（如果存在）
schtasks /delete /tn "ReelVault_Sync"    /f >nul 2>&1
schtasks /delete /tn "ReelVault_Refresh" /f >nul 2>&1

:: 添加每天凌晨 2:00 同步任务
schtasks /create ^
  /tn "ReelVault_Sync" ^
  /tr "cmd /c cd /d \"%PROJECT_DIR%\" && python tg_sync.py >> \"%PROJECT_DIR%\refresh.log\" 2>&1" ^
  /sc daily ^
  /st 02:00 ^
  /ru SYSTEM ^
  /f
if errorlevel 1 (
    echo ❌ 同步任务添加失败
) else (
    echo ✅ 已添加定时任务：每天 02:00 同步 Telegram 视频
)

:: 添加每天午夜 0:00 重启网站任务
schtasks /create ^
  /tn "ReelVault_Refresh" ^
  /tr "cmd /c \"%PROJECT_DIR%\auto_refresh.bat\"" ^
  /sc daily ^
  /st 00:00 ^
  /ru SYSTEM ^
  /f
if errorlevel 1 (
    echo ❌ 刷新任务添加失败
) else (
    echo ✅ 已添加定时任务：每天 00:00 重启网站
)

echo.
echo 查看任务列表：
schtasks /query /tn "ReelVault_Sync"
schtasks /query /tn "ReelVault_Refresh"

echo.
echo ========================================
echo  定时任务设置完成！
echo ========================================
pause
