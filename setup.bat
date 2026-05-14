@echo off
:: setup.bat — 一键安装所有依赖并启动服务
:: 第一次使用时运行这个脚本

set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo ========================================
echo  ReelVault Windows 安装脚本
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Python，请先安装 Python 3.10+
    echo    下载地址: https://www.python.org/downloads/
    echo    安装时勾选 "Add Python to PATH"
    pause
    exit /b 1
)
echo ✅ Python 已安装

:: 检查 ffmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo ⚠️  未找到 ffmpeg，缩略图功能将不可用
    echo    下载地址: https://ffmpeg.org/download.html
    echo    解压后把 bin 目录添加到系统 PATH
    echo.
) else (
    echo ✅ ffmpeg 已安装
)

:: 安装 Python 依赖
echo.
echo 正在安装 Python 依赖...
python -m pip install telethon python-dotenv fastapi uvicorn aiofiles --upgrade
if errorlevel 1 (
    echo ❌ 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)
echo ✅ 依赖安装完成

:: 创建必要目录
if not exist "videos" mkdir videos
if not exist "thumbs" mkdir thumbs
echo ✅ 目录已创建

:: 检查 .env
if not exist ".env" (
    echo.
    echo ⚠️  未找到 .env 文件，正在创建模板...
    (
        echo TG_API_ID=你的API_ID
        echo TG_API_HASH=你的API_HASH
        echo TG_PHONE=+86你的手机号
        echo TG_GROUPS=your_group_username
        echo VIDEO_DIR=videos
        echo DB_FILE=videos.json
        echo MAX_FILE_MB=500
        echo MIN_DURATION=5
        echo TG_SESSION=tg_session
    ) > .env
    echo ✅ .env 模板已创建，请用记事本编辑填入真实值
    echo    右键 .env → 用记事本打开
    notepad .env
)

echo.
echo ========================================
echo  安装完成！
echo ========================================
echo.
echo 接下来：
echo   1. 确认 .env 已填写正确
echo   2. 运行 start_sync.bat  → 开始同步视频
echo   3. 运行 start_web.bat   → 启动网站
echo   4. 浏览器访问 http://localhost:8000
echo.
pause
