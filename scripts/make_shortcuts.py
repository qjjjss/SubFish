"""生成桌面和开始菜单快捷方式，以后不用再去文件夹里找启动.bat。

用法：
    venv\\Scripts\\python scripts\\make_shortcuts.py
    venv\\Scripts\\python scripts\\make_shortcuts.py --remove   删掉快捷方式

会顺带把 extension/icons/icon128.png 转成 subfish.ico 用作图标。
生成后右键图标可以「固定到任务栏」或「固定到开始屏幕」。
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PNG = ROOT / "extension" / "icons" / "icon128.png"
ICO = ROOT / "subfish.ico"


def make_ico():
    """Windows 快捷方式只认 .ico，用 Pillow 从 PNG 转一份。"""
    try:
        from PIL import Image
    except ImportError:
        print("缺少 Pillow，跳过图标转换（快捷方式会用默认图标）")
        return None
    img = Image.open(PNG).convert("RGBA")
    img.save(ICO, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (128, 128)])
    print(f"图标: {ICO}")
    return ICO


def target():
    exe = ROOT / "venv" / "Scripts" / "pythonw.exe"
    if exe.exists():
        return str(exe)
    print("没找到 venv\\Scripts\\pythonw.exe，请先运行 安装依赖.bat")
    sys.exit(1)


def ps_create(links):
    ico = make_ico()
    icon_loc = str(ico) if ico else ""
    py = target()
    ps = (
        "$ws = New-Object -COM WScript.Shell\n"
        "$d = [Environment]::GetFolderPath('Desktop')\n"
        "$sm = Join-Path ([Environment]::GetFolderPath('ApplicationData')) "
        "'Microsoft\\Windows\\Start Menu\\Programs'\n"
        "foreach ($p in @($d, $sm)) {\n"
        "  $lnk = Join-Path $p 'SubFish.lnk'\n"
        "  $s = $ws.CreateShortcut($lnk)\n"
        f"  $s.TargetPath = '{py}'\n"
        "  $s.Arguments = '-m tray.tray'\n"
        f"  $s.WorkingDirectory = '{ROOT}'\n"
        f"  $s.IconLocation = '{icon_loc}'\n"
        "  $s.Description = 'SubFish 实时字幕'\n"
        "  $s.Save()\n"
        "  Write-Output $lnk\n"
        "}\n"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout.strip() or r.stderr.strip())


def ps_remove():
    ps = (
        "$d = [Environment]::GetFolderPath('Desktop')\n"
        "$sm = Join-Path ([Environment]::GetFolderPath('ApplicationData')) "
        "'Microsoft\\Windows\\Start Menu\\Programs'\n"
        "foreach ($p in @($d, $sm)) {\n"
        "  $lnk = Join-Path $p 'SubFish.lnk'\n"
        "  if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Output \"removed $lnk\" }\n"
        "}\n"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout.strip() or "没有找到快捷方式")


def main():
    ap = argparse.ArgumentParser(description="SubFish 快捷方式")
    ap.add_argument("--remove", action="store_true", help="删除快捷方式")
    args = ap.parse_args()
    if args.remove:
        ps_remove()
    else:
        ps_create(True)
        print("完成：桌面和开始菜单都有 SubFish 了，右键可固定到任务栏。")


if __name__ == "__main__":
    main()
