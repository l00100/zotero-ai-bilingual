# 安装本地服务

先在 Zotero 中安装本项目 XPI，然后完全退出 Zotero，再运行服务安装脚本。安装器会备份 prefs.js / extensions.json，保留其他插件及现有接口配置，不修改文库数据库。

## Windows

使用 Python 3.10–3.13，推荐 3.12。在 PowerShell 中运行 `install/安装Windows服务.ps1`，或者：

```powershell
python install/windows_setup.py
```

程序和独立环境安装到 `%LOCALAPPDATA%\HJFY-AI-Reader`，默认 Zotero 配置从 `%APPDATA%\Zotero\Zotero\profiles.ini` 读取。如需指定配置目录，使用 `--profile "配置目录"`。

手动启动：运行 `install/启动Windows服务.ps1`，或 `python install/windows_setup.py --start-only`。

## macOS

使用 Python 3.10–3.13，推荐 3.12。完全退出 Zotero 后运行 `install/安装Mac服务.command`，也可在终端执行 `bash` 加脚本路径。

程序和独立环境安装到 `~/Library/Application Support/HJFY-AI-Reader`，Zotero 配置通过 `~/Library/Application Support/Zotero/profiles.ini` 发现。有多个配置且没有唯一默认值时会要求选择。

手动启动：运行 `install/启动Mac服务.command`。源码与 Windows 测试已公开，真实 Mac 的 Zotero 阅读器和译文生成仍需进一步验证。

## 配置 AI

重新打开 Zotero，找到插件的 AI 翻译设置，填写 Base URL、准确模型 ID 和 API Key，并保存密钥。仅检查本地服务不会测试外部模型密钥。首次建议设置页码 `1-2`。

需要翻译全文时清空页码范围。默认的参考文献跳过只作用于可靠识别的区域；特殊版面或扫描件可能无法识别。

## 故障与数据位置

- 首次安装需联网下载 Python 依赖；首次翻译可能下载较大的版面模型与字体。
- 服务日志位于程序目录 `logs/service.log`。检查错误时避免公开密钥或论文内容。
- `data/` 中包含任务状态与中间 PDF；`backups/` 保存安装前的配置。不要提交这些目录到 GitHub。
- 服务只监听 8891 回环端口。已有旧版服务占用该端口时，请先退出旧服务；安装器不会强制结束进程或终止翻译任务。
- 安装器会检查 Zotero 已退出。如果中途重新打开了 Zotero，请退出后重新执行安装。
- 更新前确认后台没有正在执行的翻译任务；不要覆盖正在运行的服务代码。

官方配置目录说明：https://www.zotero.org/support/kb/profile_directory
