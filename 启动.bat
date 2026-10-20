@echo off
setlocal
cd /d %~dp0
if not exist venv (
    echo [SubFish] venv not found. Please run 安装依赖.bat first.
    pause
    exit /b 1
)
rem 托盘常驻：自动拉起服务与字幕小窗，服务日志在 logs\server.log
rem 想看实时输出（wav/mic 测试音源、排查问题）时用 启动_控制台.bat
start "" venv\Scripts\pythonw.exe -m tray.tray
echo [SubFish] 已启动，图标在系统托盘（右下角 ^）。
echo   右键图标：启动/停止服务、重新拉起小窗、开机自启、导出 SRT、退出
echo   首次使用：Chrome 加载 extension 目录，见 extension\README.md
timeout /t 3 >nul
