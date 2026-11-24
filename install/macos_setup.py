"""Install the local HJFY AI PDF service on macOS after the XPI is installed."""
from __future__ import annotations
import argparse
import configparser
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import venv

ADDON_ID = "zotero-hjfy-split-reader-cn@leisongju.github.io"
PREFIX = "extensions.zotero.hjfySplitReaderCN."
SERVICE_FILES = ("bridge.py", "worker.py", "references.py", "requirements.txt")


def supported_python(version=None):
    version = version or sys.version_info
    return (3, 10) <= tuple(version[:2]) < (3, 14)


def choose_profile(zotero_root, explicit=None, choose=input):
    if explicit:
        profile = Path(explicit).expanduser().resolve()
        if not (profile / "prefs.js").is_file():
            raise RuntimeError("指定目录中没有 prefs.js，请选择 Zotero 配置目录。")
        return profile
    ini = zotero_root / "profiles.ini"
    if not ini.is_file():
        raise RuntimeError("尚未找到 Zotero 配置。请先安装并打开 Zotero，装入 XPI 后完全退出，再运行此脚本。")
    config = configparser.ConfigParser(interpolation=None)
    config.read(ini, encoding="utf-8-sig")
    candidates = []
    for section in config.sections():
        if not section.startswith("Profile") or not config.has_option(section, "Path"):
            continue
        raw = Path(config.get(section, "Path"))
        profile = (zotero_root / raw if config.getboolean(section, "IsRelative", fallback=True) else raw).resolve()
        if (profile / "prefs.js").is_file():
            candidates.append((profile, config.getboolean(section, "Default", fallback=False)))
    defaults = [path for path, default in candidates if default]
    if len(defaults) == 1:
        return defaults[0]
    for section in config.sections():
        if section.startswith("Install") and config.has_option(section, "Default"):
            path = (zotero_root / config.get(section, "Default")).resolve()
            if path in [candidate for candidate, _ in candidates]:
                return path
    if len(candidates) == 1:
        return candidates[0][0]
    if not candidates:
        raise RuntimeError("未找到有效的 Zotero 配置目录。")
    print("发现多个 Zotero 配置，请选择你要使用的一个：")
    for index, (path, _) in enumerate(candidates, 1):
        print(f"  {index}. {path}")
    try:
        index = int(choose("输入序号：")) - 1
        if index < 0 or index >= len(candidates):
            raise ValueError()
        return candidates[index][0]
    except (ValueError, EOFError) as exc:
        raise RuntimeError("没有选择有效的配置目录。") from exc


def require_zotero_closed():
    result = subprocess.run(["/usr/bin/pgrep", "-i", "-x", "zotero"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        raise RuntimeError("请用 Command+Q 完全退出 Zotero，再运行本脚本。不会强制结束 Zotero。")
    if result.returncode != 1:
        raise RuntimeError("无法确认 Zotero 是否已退出，请检查进程后重试。")


def atomic_write(path, text):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".ai-reader-", suffix=".tmp", delete=False) as file:
        file.write(text)
        temporary = Path(file.name)
    temporary.replace(path)


def configure_profile(profile, app_root, token, python_relative=".venv/bin/python3"):
    prefs_path = profile / "prefs.js"
    config_path = profile / "extensions.json"
    config = json.loads(config_path.read_text("utf-8")) if config_path.is_file() else None
    addons = [addon for addon in (config or {}).get("addons", []) if addon.get("id") == ADDON_ID]
    installed = profile / "extensions" / (ADDON_ID + ".xpi")
    if not installed.is_file() and not addons:
        raise RuntimeError("请先在 Zotero 的插件管理器里从文件安装随包的 .xpi，再退出 Zotero运行本脚本。")
    backup = app_root / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True)
    shutil.copy2(prefs_path, backup / "prefs.js")
    if config_path.is_file():
        shutil.copy2(config_path, backup / "extensions.json")
    settings = {
        "aiBridgeToken": token,
        "aiPythonPath": str(app_root / python_relative),
        "aiServicePath": str(app_root / "service/bridge.py"),
        "aiStatePath": str(app_root / "data"),
    }
    text = prefs_path.read_text("utf-8")
    for key, value in settings.items():
        name = PREFIX + key
        text = re.sub(r'^user_pref\("' + re.escape(name) + r'",.*\);\r?\n?', "", text, flags=re.MULTILINE)
        text += "\nuser_pref(" + json.dumps(name) + ", " + json.dumps(value, ensure_ascii=False) + ");\n"
    atomic_write(prefs_path, text)
    # Only this local fork is kept off upstream automatic updates.
    if config is not None and addons:
        for addon in addons:
            addon["applyBackgroundUpdates"] = 0
        atomic_write(config_path, json.dumps(config, ensure_ascii=False, separators=(",", ":")))
    return backup


def health(app_root):
    token_file = app_root / "data/bridge-token.txt"
    if not token_file.is_file():
        return None
    request = Request("http://127.0.0.1:8891/health", headers={"Authorization": "Bearer " + token_file.read_text("ascii").strip()})
    try:
        with urlopen(request, timeout=2) as response:
            data = json.load(response)
            return data if data.get("protocol") == 1 else None
    except (OSError, URLError, ValueError):
        return None


def start_service(app_root, python_relative=".venv/bin/python3"):
    ready = health(app_root)
    if ready:
        print("本地服务已运行：" + str(ready.get("engine", "")))
        return
    python = app_root / python_relative
    bridge = app_root / "service/bridge.py"
    if not python.is_file() or not bridge.is_file():
        raise RuntimeError("尚未安装本地服务，请先运行“安装Mac服务.command”。")
    log_dir = app_root / "logs"
    log_dir.mkdir(exist_ok=True)
    with (log_dir / "service.log").open("ab") as log:
        process = subprocess.Popen([str(python), str(bridge), "--state-dir", str(app_root / "data")],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   cwd=app_root, close_fds=True, start_new_session=True)
    for _ in range(20):
        time.sleep(.5)
        if health(app_root):
            print("本地服务就绪：127.0.0.1:8891")
            return
        if process.poll() is not None:
            break
    raise RuntimeError("本地服务启动失败。请查看安装目录 logs/service.log；检查 8891 端口是否已被其他服务占用。")


def install(package_root, app_root, explicit_profile=None):
    require_zotero_closed()
    profile = choose_profile(Path.home() / "Library/Application Support/Zotero", explicit_profile)
    if not (profile / "extensions" / (ADDON_ID + ".xpi")).is_file():
        config_path = profile / "extensions.json"
        config = json.loads(config_path.read_text("utf-8")) if config_path.is_file() else {}
        if not any(addon.get("id") == ADDON_ID for addon in config.get("addons", [])):
            raise RuntimeError("请先在 Zotero 中安装随包 .xpi 插件，再用 Command+Q 退出 Zotero 后运行此脚本。")
    source = package_root / "service"
    if not all((source / name).is_file() for name in SERVICE_FILES):
        raise RuntimeError("安装包缺少 service 文件，请完整解压 ZIP 后再运行。")
    if health(app_root):
        raise RuntimeError("本地服务正在运行。此次安装已停止，以免覆盖正在执行的程序；如需重装，请先退出服务。")
    destination = app_root / "service"
    destination.mkdir(parents=True, exist_ok=True)
    for name in SERVICE_FILES:
        shutil.copy2(source / name, destination / name)
    environment = app_root / ".venv"
    if not (environment / "bin/python3").is_file():
        print("创建独立 Python 环境…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin/python3"
    print("安装 PDF2zh-next / BabelDOC 依赖，首次可能需要数分钟…", flush=True)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary",
                    "-r", str(destination / "requirements.txt")], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    state = app_root / "data"
    state.mkdir(exist_ok=True)
    token_path = state / "bridge-token.txt"
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), "ascii")
        token_path.chmod(0o600)
    require_zotero_closed()  # Check again after dependency installation.
    backup = configure_profile(profile, app_root, token_path.read_text("ascii").strip())
    start_service(app_root)
    print("\n安装完成。重新打开 Zotero，在 AI 翻译设置中填写接口地址、模型名称和 API Key。")
    print("程序位置：" + str(app_root))
    print("配置备份：" + str(backup))
    print("安装包可以移走；程序运行所需文件已经复制到上述程序位置。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-only", action="store_true")
    parser.add_argument("--profile", help="自定义 Zotero 配置目录（通常无需指定）")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise RuntimeError("此安装脚本仅用于 macOS。Windows 请使用原有安装。")
    if not supported_python():
        raise RuntimeError("需要 Python 3.10–3.13，建议安装 Python 3.12 后再运行。")
    app_root = Path.home() / "Library/Application Support/HJFY-AI-Reader"
    if args.start_only:
        start_service(app_root)
    else:
        package_root = Path(__file__).resolve().parent
        if not (package_root / "service").is_dir():
            package_root = package_root.parent
        install(package_root, app_root, args.profile)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print("\n安装未完成：" + str(error), file=sys.stderr)
        sys.exit(1)
