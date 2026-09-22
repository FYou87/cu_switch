# Witch

给 Cursor 用的中转站切换器。主界面按 CC Switch 的供应商页排：顶栏（设置、本地代理开关、Cursor）、供应商卡片、启用 / 使用中，以及编辑、复制、测速、删除。托盘里也能直接切。

## 免安装（Windows / macOS）

解压即用，不用装 Python。

| 系统 | 打开方式 |
| --- | --- |
| Windows 10/11 x64 | 解压后双击 `Witch.exe` |
| macOS Apple 芯片（M1/M2/M3/M4） | 解压后双击 `Witch.app` |
| macOS Intel | 解压后双击 `Witch.app` |

自己打包：

```bash
.venv/bin/python scripts/pack_portable.py windows-x64 macos-arm64 macos-x64
```

产物在 `dist/portable/`。Windows 若被 SmartScreen 拦截，选“仍要运行”。macOS 第一次按住 Control 点图标选打开。

## 源码运行

本机有 Python 3.10+ 时：

| 系统 | 怎么开 |
| --- | --- |
| Windows | `Witch.bat` |
| macOS | `Witch.command` |
| Linux | `./Witch.sh` |

网关：`127.0.0.1:43187`。

## Cursor

Settings → Models：打开 OpenAI API Key 和 Override OpenAI Base URL。地址和 Key 在 Witch 齿轮里复制。之后只在 Witch 点启用或托盘切换。

## 数据

免安装包写在软件目录的 `data/witch.json`。源码运行默认：

- Windows：`%APPDATA%\Witch\witch.json`
- macOS：`~/Library/Application Support/Witch/witch.json`
- Linux：`~/.config/witch/witch.json`

也可用 `WITCH_DATA` 指定文件。

```bash
.venv/bin/python -m unittest discover -s tests -v
```
