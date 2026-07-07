@echo off
chcp 65001 >nul
title Code Wiki — Full Stack

echo ========================================
echo   Code Wiki 开发环境启动
echo ========================================
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%code-wiki-frontend

:: ── Backend ──
echo [1/2] 启动 Python 后端 (port 8000) ...
start "Code Wiki Backend" cmd /c "cd /d "%BACKEND%" && python main.py"

:: ── Frontend ──
echo [2/2] 启动 Tauri 前端 (vite:3000) ...
start "Code Wiki Frontend" cmd /c "cd /d "%FRONTEND%" && cargo tauri dev"

echo.
echo 后端: http://localhost:8000
echo 前端: http://localhost:3000
echo.
echo 关闭本窗口不影响前后端运行。
echo ========================================
pause
