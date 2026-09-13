@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境：%~dp0.venv\Scripts\python.exe
    echo 请先在项目根目录执行：python -m venv .venv
    pause
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -m PyInstaller --onefile --noconsole --name pomodoro_app --clean pomodoro_app.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方输出。
    pause
    exit /b 1
)

echo.
echo 打包完成，产物在 dist\pomodoro_app.exe
pause