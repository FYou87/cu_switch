#!/usr/bin/env python3
"""Build unzip-and-run Witch folders for Windows and macOS."""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
CPU_TYPE_X86_64 = 0x01000007
CPU_TYPE_ARM64 = 0x0100000C

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from witch import __version__ as VERSION
CACHE = ROOT / "build" / "portable-cache"
OUT = ROOT / "dist" / "portable"
PBS_TAG = "20260901"
PBS_VER = "3.12.14"
PYSIDE = "6.11.2"
PREFIX = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}"

TARGETS = {
    "windows-x64": {
        "python": f"cpython-{PBS_VER}+{PBS_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
        "pip_platform": "win_amd64",
        "kind": "windows",
    },
    "macos-arm64": {
        "python": f"cpython-{PBS_VER}+{PBS_TAG}-aarch64-apple-darwin-install_only_stripped.tar.gz",
        "pip_platform": "macosx_13_0_universal2",
        "kind": "macos",
        "thin": "arm64",
    },
    "macos-x64": {
        "python": f"cpython-{PBS_VER}+{PBS_TAG}-x86_64-apple-darwin-install_only_stripped.tar.gz",
        "pip_platform": "macosx_13_0_universal2",
        "kind": "macos",
        "thin": "x86_64",
    },
}


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    print(f"download {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)
    return dest


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd)


def fetch_wheels(platform: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.glob("PySide6_Essentials-*.whl")) and any(dest.glob("shiboken6-*.whl")):
        return
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            f"PySide6_Essentials=={PYSIDE}",
            f"shiboken6=={PYSIDE}",
            "--dest",
            str(dest),
            "--only-binary=:all:",
            "--python-version",
            "312",
            "--implementation",
            "cp",
            "--abi",
            "cp312",
            "--platform",
            platform,
        ]
    )


def unpack_python(archive: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(dest, filter="data")
    python_dir = dest / "python"
    if not python_dir.exists():
        raise RuntimeError(f"no python/ in {archive.name}")
    return python_dir


def site_packages(python_dir: Path, kind: str) -> Path:
    if kind == "windows":
        return python_dir / "Lib" / "site-packages"
    return python_dir / "lib" / "python3.12" / "site-packages"


def install_wheels(wheel_dir: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"no wheels in {wheel_dir}")
    for wheel in wheels:
        print(f"extract {wheel.name}")
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(target)


def thin_macho(path: Path, arch: str) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 8:
        return False
    magic = struct.unpack(">I", data[:4])[0]
    if magic not in (FAT_MAGIC, FAT_MAGIC_64):
        return False
    want = CPU_TYPE_ARM64 if arch == "arm64" else CPU_TYPE_X86_64
    nfat = struct.unpack(">I", data[4:8])[0]
    entry = 32 if magic == FAT_MAGIC_64 else 20
    off = 8
    for _ in range(nfat):
        chunk = data[off : off + entry]
        if len(chunk) < 20:
            return False
        cputype, _cpu_subtype, offset, size = struct.unpack(">IIII", chunk[:16])
        if cputype == want and offset + size <= len(data):
            path.write_bytes(data[offset : offset + size])
            return True
        off += entry
    return False


def thin_tree(root: Path, arch: str) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            thin_macho(path, arch)


def copy_witch(site: Path) -> None:
    dest = site / "witch"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        ROOT / "witch",
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def write_windows_launchers(root: Path) -> None:
    (root / "portable").write_text("witch\n", encoding="utf-8")
    (root / "Witch.bat").write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "if exist python\\pythonw.exe (\r\n"
        "  start \"\" python\\pythonw.exe -m witch\r\n"
        ") else (\r\n"
        "  python\\python.exe -m witch\r\n"
        ")\r\n",
        encoding="utf-8",
    )
    (root / "Witch.vbs").write_text(
        'Set sh = CreateObject("Wscript.Shell")\r\n'
        'Set fs = CreateObject("Scripting.FileSystemObject")\r\n'
        'dir = fs.GetParentFolderName(WScript.ScriptFullName)\r\n'
        'sh.CurrentDirectory = dir\r\n'
        'sh.Run """" & dir & "\\python\\pythonw.exe"" -m witch", 0, False\r\n',
        encoding="utf-8",
    )
    exe = ROOT / "packaging" / "Witch.exe"
    if exe.exists():
        shutil.copy2(exe, root / "Witch.exe")
    (root / "使用说明.txt").write_text(
        "解压整个文件夹，双击 Witch.exe（或 Witch.vbs）。不用装 Python。\r\n"
        "Windows 10/11。SmartScreen 若拦截，选“仍要运行”。\r\n"
        "顶栏 API：不用登录 Cursor。Agent 和 IDE 都走当前中转站，Cursor 会退出后重新打开。\r\n"
        "顶栏 登录：恢复原版 Cursor，用账号登录。\r\n"
        "Cursor 装在默认位置即可。若提示没有权限，右键 Witch，用管理员身份运行。\r\n"
        "中转站的地址和 Key 写在供应商卡片里。顶栏切到 API 后，Cursor 会走当前这张卡片。\r\n",
        encoding="utf-8",
    )


def write_macos_app(root: Path, python_dir: Path) -> None:
    app = root / "Witch.app"
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    shutil.move(str(python_dir), resources / "python")
    (resources / "portable").write_text("witch\n", encoding="utf-8")
    (app / "Contents" / "Info.plist").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Witch</string>
  <key>CFBundleDisplayName</key><string>Witch</string>
  <key>CFBundleIdentifier</key><string>local.witch.switch</string>
  <key>CFBundleVersion</key><string>{VERSION}</string>
  <key>CFBundleShortVersionString</key><string>{VERSION}</string>
  <key>CFBundleExecutable</key><string>Witch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    launcher = macos / "Witch"
    launcher.write_text(
        "#!/bin/bash\n"
        'ROOT="$(cd "$(dirname "$0")/../Resources" && pwd)"\n'
        'export PATH="$ROOT/python/bin:$PATH"\n'
        'exec "$ROOT/python/bin/python3" -m witch\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    (root / "使用说明.txt").write_text(
        "解压后双击 Witch.app。第一次若提示“无法打开”，按住 Control 点图标选打开。\n"
        "不需要安装 Python。\n"
        "顶栏 API：不用登录 Cursor。Agent 和 IDE 都走当前中转站，Cursor 会退出后重新打开。\n"
        "顶栏 登录：恢复原版 Cursor，用账号登录。\n"
        "中转站的地址和 Key 写在供应商卡片里。顶栏切到 API 后，Cursor 会走当前这张卡片。\n",
        encoding="utf-8",
    )


def zip_dir(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for path in source.rglob("*"):
            if path.is_file():
                handle.write(path, path.relative_to(source.parent))


def compile_windows_exe() -> None:
    gcc = shutil.which("x86_64-w64-mingw32-gcc") or shutil.which("x86_64-w64-mingw32-cc")
    out = ROOT / "packaging" / "Witch.exe"
    src = ROOT / "packaging" / "witch_launcher.c"
    if not gcc:
        print("no mingw, skip Witch.exe")
        return
    try:
        run([gcc, "-O2", "-s", "-mwindows", str(src), "-lshlwapi", "-o", str(out)])
    except subprocess.CalledProcessError:
        print("Witch.exe compile failed, using VBS launcher")


def build_one(name: str, spec: dict) -> Path:
    archive = download(f"{PREFIX}/{spec['python']}", CACHE / spec["python"])
    wheels = CACHE / f"wheels-{name}"
    fetch_wheels(spec["pip_platform"], wheels)
    work = OUT / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    python_dir = unpack_python(archive, work / "_py")
    site = site_packages(python_dir, spec["kind"])
    install_wheels(wheels, site)
    copy_witch(site)
    if spec.get("thin"):
        thin_tree(site, spec["thin"])
    if spec["kind"] == "windows":
        # flatten: Witch/python + launchers
        final = work / "Witch"
        final.mkdir()
        shutil.move(str(python_dir), final / "python")
        shutil.rmtree(work / "_py")
        write_windows_launchers(final)
        zip_path = OUT / f"Witch-{VERSION}-{name}.zip"
        zip_dir(final, zip_path)
        return zip_path
    final = work / "Witch"
    final.mkdir()
    write_macos_app(final, python_dir)
    shutil.rmtree(work / "_py", ignore_errors=True)
    zip_path = OUT / f"Witch-{VERSION}-{name}.zip"
    zip_dir(final, zip_path)
    return zip_path


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    compile_windows_exe()
    wanted = sys.argv[1:] or list(TARGETS)
    built = []
    for name in wanted:
        if name not in TARGETS:
            raise SystemExit(f"unknown target {name}; choose from {', '.join(TARGETS)}")
        path = build_one(name, TARGETS[name])
        built.append(path)
        print("built", path, "size", path.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
