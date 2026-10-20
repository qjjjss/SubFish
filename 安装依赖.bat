@echo off
setlocal
cd /d %~dp0
where py >nul 2>nul
if %errorlevel%==0 (set "PYCMD=py -3") else (set "PYCMD=python")
echo [SubFish] using: %PYCMD%
%PYCMD% -m venv venv
if errorlevel 1 (
    echo [SubFish] venv creation failed. Please install Python 3.10+ first.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
rem 默认走清华镜像（国内快；换回官方源把下面 -i 参数删掉即可）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [SubFish] dependency install failed. Check the log above.
    pause
    exit /b 1
)
echo.
if not exist server\models\whisper-medium (
    echo [SubFish] 正在下载 Whisper medium 模型（约 1.5G，支持断点续传）...
    python scripts\fetch_model.py
    if errorlevel 1 (
        echo [SubFish] 模型下载失败，可稍后手动运行 scripts\fetch_model.py
    )
) else (
    echo [SubFish] 模型已存在，跳过下载。
)
echo.
echo [SubFish] 正在创建桌面/开始菜单快捷方式...
python scripts\make_shortcuts.py
echo.
echo [SubFish] done. 以后双击桌面上的 SubFish 图标即可（或开始菜单里搜 SubFish）。
pause
