#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "此脚本仅用于 macOS。"
  exit 1
fi
app_root="${HOME}/Library/Application Support/HJFY-AI-Reader"
python_bin="${app_root}/.venv/bin/python3"
if [[ ! -x "$python_bin" ]]; then
  echo "请先运行“安装Mac服务.command”。"
  read -r -p "按回车键退出…" _
  exit 1
fi
"$python_bin" macos_setup.py --start-only
read -r -p "按回车键关闭此窗口…" _
