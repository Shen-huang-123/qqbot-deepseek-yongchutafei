@echo off
chcp 65001 >nul
title QQ ChatBot 启动
cd /d "%~dp0"

echo.
echo ╔══════════════════════════════════════╗
echo ║     QQ AI ChatBot 一键启动          ║
echo ╚══════════════════════════════════════╝
echo.

:: 删除上次的二维码
del /Q "%~dp0qrcode.png" 2>nul

:: ========== 步骤1：注入 NapCat 到 QQ NT ==========
echo [1/3] 注入 NapCat 到 QQ NT...
set "APP_DIR=C:\Program Files\Tencent\QQNT\versions\9.9.32-51246\resources\app"
set "NAPCAT_DIR=C:\Users\z8596\Downloads\NapCatQQ_new"

copy /Y "%NAPCAT_DIR%\qqnt.json" "%APP_DIR%\package.json" >nul
echo (async () =^> {await import("file:///C:/Users/z8596/Downloads/NapCatQQ_new/napcat.mjs")})() > "%APP_DIR%\loadNapCat.js"
echo    已注入

:: ========== 步骤2：启动 AI 服务 ==========
echo [2/3] 启动 AI 服务...
start "QQ-AI-Server" "D:\26shixun\Anaconda\python.exe" server.py

:: 等 AI 服务就绪
echo    等待 AI 服务启动...
timeout /t 3 /nobreak >nul

:: ========== 步骤3：启动 QQ NT ==========
echo [3/3] 启动 QQ NT...
start "" "C:\Program Files\Tencent\QQNT\QQ.exe"
echo    等待二维码生成...

:: 等 NapCat 生成二维码（最多等 20 秒）
set /a count=0
:wait_qr
timeout /t 2 /nobreak >nul
set /a count+=2
if exist "%NAPCAT_DIR%\cache\qrcode.png" goto copy_qr
if %count% LSS 20 goto wait_qr

:copy_qr
if exist "%NAPCAT_DIR%\cache\qrcode.png" (
    copy /Y "%NAPCAT_DIR%\cache\qrcode.png" "%~dp0qrcode.png" >nul
    echo    二维码已保存: qrcode.png
) else (
    echo    二维码未生成，请查看终端
)

echo.
echo ╔══════════════════════════════════════╗
echo ║  启动完成！                         ║
echo ╠══════════════════════════════════════╣
echo ║  扫码登录: qrcode.png               ║
echo ║  AI 服务:  http://127.0.0.1:8765    ║
echo ║  聊天面板: http://127.0.0.1:8765/chat║
echo ╚══════════════════════════════════════╝
echo.
pause
