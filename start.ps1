# QQ ChatBot 启动脚本
# 用法：.\start.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  QQ ChatBot - AI 聊天机器人" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Python
$PythonPath = $null
if (Test-Path "D:\26shixun\Anaconda\python.exe") {
    $PythonPath = "D:\26shixun\Anaconda\python.exe"
} else {
    $PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
}

if (-not $PythonPath) {
    Write-Host "[ERROR] 未找到 Python，请安装 Python 3.11+" -ForegroundColor Red
    pause
    exit 1
}
Write-Host "[OK] Python: $PythonPath" -ForegroundColor Green

# 检查 .env
if (-not (Test-Path ".env")) {
    Write-Host "[INFO] 未找到 .env，从 .env.example 复制..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "[INFO] 请编辑 .env 填写 AI_API_KEY 后重新运行" -ForegroundColor Yellow
    notepad ".env"
    pause
    exit 0
}

# 安装依赖
Write-Host "[1/3] 安装依赖..." -ForegroundColor Yellow
& $PythonPath -m pip install -r requirements.txt -q 2>$null
Write-Host "[OK] 依赖就绪" -ForegroundColor Green

# 启动服务
Write-Host "[2/3] 启动 AI 服务..." -ForegroundColor Yellow
Write-Host "  服务地址: http://127.0.0.1:8765" -ForegroundColor Gray
Write-Host "  聊天面板: http://127.0.0.1:8765/chat" -ForegroundColor Gray
Write-Host "  健康检查: http://127.0.0.1:8765/health" -ForegroundColor Gray
Write-Host ""

& $PythonPath server.py

pause
