@echo off
setlocal
cd /d %~dp0
if not exist venv (
    echo [SubFish] venv not found. Please run 安装依赖.bat first.
    pause
    exit /b 1
)
rem 控制台版：看得到实时日志，适合调试
rem   启动_控制台.bat --source wav:test_audio\en_sample.wav --loop
rem   启动_控制台.bat --source mic
call venv\Scripts\activate.bat
python -m server.main %*
pause
