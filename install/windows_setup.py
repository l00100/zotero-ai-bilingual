"""Windows companion-service installer; never touches Zotero's library database."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import venv

from macos_setup import (ADDON_ID, SERVICE_FILES, choose_profile, configure_profile,
                         health, start_service, supported_python)


def require_zotero_closed():
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq zotero.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("无法检查 Zotero 进程，请确认已完全退出后重试。")
    if b"zotero.exe" in result.stdout.lower():
        raise RuntimeError("请先完全退出 Zotero，再运行安装脚本。不会强制结束 Zotero。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile")
    parser.add_argument("--start-only", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or not supported_python():
        raise RuntimeError("需要 Windows 和 Python 3.10–3.13，建议使用 Python 3.12。")
    app_root = Path(os.environ["LOCALAPPDATA"]) / "HJFY-AI-Reader"
    if args.start_only:
        start_service(app_root, ".venv/Scripts/pythonw.exe")
        return
    require_zotero_closed()
    zotero_root = Path(os.environ["APPDATA"]) / "Zotero/Zotero"
    profile = choose_profile(zotero_root, args.profile)
    installed = profile / "extensions" / (ADDON_ID + ".xpi")
    config_path = profile / "extensions.json"
    config = json.loads(config_path.read_text("utf-8")) if config_path.is_file() else {}
    if not installed.is_file() and not any(addon.get("id") == ADDON_ID for addon in config.get("addons", [])):
        raise RuntimeError("请先在 Zotero 中安装本项目的 XPI，然后退出 Zotero。")
    if health(app_root):
        raise RuntimeError("此安装目录的服务正在运行。请先退出服务再更新，以免覆盖正在执行的程序。")
    source = Path(__file__).resolve().parent.parent / "service"
    if not all((source / name).is_file() for name in SERVICE_FILES):
        raise RuntimeError("缺少服务源码，请完整解压安装包。")
    destination = app_root / "service"
    destination.mkdir(parents=True, exist_ok=True)
    for name in SERVICE_FILES:
        shutil.copy2(source / name, destination / name)
    environment = app_root / ".venv"
    if not (environment / "Scripts/python.exe").is_file():
        print("创建独立 Python 环境…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "Scripts/python.exe"
    print("安装排版引擎，首次可能需要数分钟…", flush=True)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary",
                    "-r", str(destination / "requirements.txt")], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    state = app_root / "data"
    state.mkdir(exist_ok=True)
    token_path = state / "bridge-token.txt"
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), "ascii")
    require_zotero_closed()
    backup = configure_profile(profile, app_root, token_path.read_text("ascii").strip(), ".venv/Scripts/pythonw.exe")
    start_service(app_root, ".venv/Scripts/pythonw.exe")
    print("安装完成。重新打开 Zotero，在插件设置中填写 AI 接口信息。")
    print("本地服务位置：" + str(app_root))
    print("配置备份：" + str(backup))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
