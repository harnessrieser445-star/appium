@echo off
chcp 65001 >nul
echo ========================================
echo   Appium 自动化测试平台启动脚本
echo ========================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 检查虚拟环境是否存在
if exist "venv\Scripts\python.exe" (
    echo [INFO] 使用虚拟环境启动...
    set PYTHON=venv\Scripts\python.exe
) else (
    echo [WARN] 未找到虚拟环境，使用系统Python...
    set PYTHON=python
)

echo.
echo [INFO] 正在启动服务...
echo [INFO] 服务地址: http://127.0.0.1:5001
echo [INFO] 按 Ctrl+C 停止服务
echo.

%PYTHON% app.py

pause
