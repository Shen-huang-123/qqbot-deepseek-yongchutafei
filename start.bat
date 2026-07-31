@echo off
chcp 65001 >nul
title QQ ChatBot
cd /d "%~dp0"

echo.
echo ==========================================
echo   QQ ChatBot 启动中...
echo ==========================================
echo.

echo [1/3] 安装依赖...
pip install -r requirements.txt -q 2>nul

echo [2/3] 启动 AI 服务...
start "" "D:\26shixun\Anaconda\python.exe" server.py
timeout /t 3 >nul

echo [3/3] 启动剪贴板助手...
start "" "D:\26shixun\Anaconda\python.exe" clipboard_bridge.py

echo.
echo ==========================================
echo   启动完成！
echo   聊天面板: http://127.0.0.1:8765/chat
echo.
echo   使用剪贴板助手:
echo   1. QQ Ctrl+C 消息
echo   2. 自动获取 AI 回复
echo   3. Ctrl+V 贴回 QQ
echo ==========================================
pause
