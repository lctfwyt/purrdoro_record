@echo off
REM 番茄钟记录 - 一键打包脚本
cd /d %~dp0
.\.venv\Scripts\python.exe -m PyInstaller --onefile --noconsole --name pomodoro_app --clean pomodoro_app.py
echo.
echo 打包完成，产物在 dist\pomodoro_app.exe
pause
