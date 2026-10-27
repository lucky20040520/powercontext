#!/usr/bin/env bash
# Linux / WSL 初始化脚本：安装并启动 PowerContext Server
# 用法：bash init_powercontext.sh
set -e

echo "==> 1/3 检查 uv ..."
if ! command -v uv >/dev/null 2>&1; then
  echo "    未检测到 uv，正在安装（官方安装脚本）..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

echo "==> 2/3 安装 powercontext[cli,server]（master 分支）..."
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"

echo "==> 3/3 启动 PowerContext Server ..."
nohup powercontext server run > /tmp/powercontext-server.log 2>&1 &
sleep 8

if curl --fail --silent http://127.0.0.1:8000/health/live; then
  echo ""
  echo "健康检查通过，PowerContext 已就绪。可在 Dify 中导入 DSL 开始体验。"
  echo "Server 日志：/tmp/powercontext-server.log"
else
  echo "健康检查未通过，请查看 /tmp/powercontext-server.log，或手动运行：powercontext server run"
fi
