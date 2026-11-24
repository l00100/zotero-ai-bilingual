"""Build source-based platform bundles without personal/runtime data."""
from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "package.json").read_text("utf-8"))["version"]
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)
xpies = list((ROOT / ".scaffold/build").glob("*.xpi"))
if len(xpies) != 1:
    raise RuntimeError("Run npm run build before packaging; expected exactly one XPI")
with zipfile.ZipFile(xpies[0]) as archive:
    if json.loads(archive.read("manifest.json"))["version"] != VERSION:
        raise RuntimeError("XPI and package versions differ")

for platform in ("macOS", "Windows"):
    name = f"Zotero-AI-Bilingual-{platform}-{VERSION}"
    files = [(xpies[0], xpies[0].name), (ROOT / "LICENSE", "LICENSE"),
             (ROOT / "NOTICE.md", "NOTICE.md"), (ROOT / "README.md", "README.md"),
             (ROOT / "docs/images/ai-bilingual-preview.png", "docs/images/ai-bilingual-preview.png"),
             (ROOT / "docs/INSTALL.md", "docs/INSTALL.md")]
    for file in (ROOT / "service").glob("*"):
        if file.is_file() and file.suffix in (".py", ".txt"):
            files.append((file, "service/" + file.name))
    installers = ("macos_setup.py", "安装Mac服务.command", "启动Mac服务.command") if platform == "macOS" else (
        "macos_setup.py", "windows_setup.py", "安装Windows服务.ps1", "启动Windows服务.ps1")
    for name_in_install in installers:
        files.append((ROOT / "install" / name_in_install, "install/" + name_in_install))
    output = DIST / (name + ".zip")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, relative in files:
            info = zipfile.ZipInfo(name + "/" + relative)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if relative.endswith(".command") else 0o100644) << 16
            archive.writestr(info, source.read_bytes().replace(b"\r\n", b"\n") if source.suffix != ".xpi" else source.read_bytes())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any(part in file.lower() for file in archive.namelist() for part in ("prefs.js", "logins.json", "bridge-token", ".venv", ".pdf", ".sqlite", "requirements-lock"))
    print(output.name)
