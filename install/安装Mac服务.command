#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "此脚本仅用于 macOS。"
  exit 1
fi
python_bin=""
for candidate in python3.12 python3.13 python3.11 python3.10 python3 \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys;sys.exit(0 if (3,10)<=sys.version_info[:2]<(3,14) else 1)' 2>/dev/null; then
    python_bin="$(command -v "$candidate")"
    break
  fi
done
if [[ -z "$python_bin" ]]; then
  echo "没有找到 Python 3.10–3.13。请先安装 Python 3.12（python.org），再运行。"
  echo "Python 3.14 和 Mac 自带的旧版 Python 不适用于这个翻译引擎。"
  read -r -p "按回车键退出…" _
  exit 1
fi
"$python_bin" macos_setup.py "$@"
echo ""
read -r -p "按回车键关闭此窗口…" _
