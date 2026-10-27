# -*- coding: utf-8 -*-
# PowerShell 初始化脚本：安装并启动 PowerContext Server（Windows）
# 用法：powershell -ExecutionPolicy Bypass -File init_powercontext.ps1
# 说明：Windows 上 PowerContext 为 experimental 支持；失败时建议改用 WSL/Linux 执行 init_powercontext.sh

$ErrorActionPreference = "Stop"

Write-Host "==> 1/3 检查 uv ..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "    未检测到 uv，正在安装（使用官方安装脚本）..."
    Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" | Invoke-Expression
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}
uv --version

Write-Host "==> 2/3 安装 powercontext[cli,server]（master 分支）..."
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"

Write-Host "==> 3/3 启动 PowerContext Server ..."
Write-Host "    正在后台启动 server，健康检查地址 http://127.0.0.1:8000/health/live"
Start-Process -FilePath "powercontext" -ArgumentList "server", "run" -WindowStyle Hidden

Start-Sleep -Seconds 8

try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health/live" -TimeoutSec 10 -UseBasicParsing
    Write-Host "健康检查通过：HTTP $($resp.StatusCode) - $($resp.Content)"
    Write-Host "PowerContext 已就绪。可在 Dify 中导入 DSL 开始体验。"
} catch {
    Write-Host "健康检查未通过：$($_.Exception.Message)"
    Write-Host "请手动运行：powercontext server run，然后再次检查 http://127.0.0.1:8000/health/live"
}
