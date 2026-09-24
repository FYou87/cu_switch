# Witch

给 Cursor 用的中转站切换器。主界面按 CC Switch 的供应商页排：顶栏（设置、本地代理、API / 登录）、供应商卡片、启用 / 使用中，以及编辑、复制、测速、删除。托盘里也能直接切。

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

顶栏在 **API** 和 **登录** 之间切换。

- **API**：打开 Cursor 自带的本地 API。Agent 和 IDE 都走 Witch 里当前启用的中转站，不用登录 Cursor 账号。切换时会退出并重新打开 Cursor。
- **登录**：把 Cursor 程序恢复成原版，用账号登录。

Witch 会先备份被改过的 Cursor 文件，再写回去。Cursor 更新之后如果 API 模式掉了，再点一次 API。

中转站的地址和 Key 写在供应商卡片里。模型不用手填：编辑时点「获取模型列表」，再从下拉里选。顶栏切到 API 后，Cursor 会直接走当前这张卡片。日常换站，在卡片或托盘里点启用就行。

## 数据

免安装包写在软件目录的 `data/witch.json`。源码运行默认：

- Windows：`%APPDATA%\Witch\witch.json`
- macOS：`~/Library/Application Support/Witch/witch.json`
- Linux：`~/.config/witch/witch.json`

也可用 `WITCH_DATA` 指定文件。

```bash
.venv/bin/python -m unittest discover -s tests -v
```
