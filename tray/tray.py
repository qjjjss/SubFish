"""SubFish 系统托盘常驻：替代控制台窗口，一键管理服务与小窗。

用法（项目根目录）：
    venv\\Scripts\\pythonw.exe -m tray.tray     无控制台（快捷方式用它）
    venv\\Scripts\\python -m tray.tray           带日志输出，排查时用

日常别去文件夹找 bat：跑一次 scripts\\make_shortcuts.py 会在桌面和开始菜单
生成 SubFish 快捷方式，之后双击图标即可（还可以右键固定到任务栏/开始屏幕）。

托盘菜单：
    SubFish · 状态          当前服务状态（不可点）
    启动服务 / 停止服务
    重新拉起字幕小窗
    打开字幕日志目录
    退出                    一并停掉服务和小窗
"""
import json
import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_DIR = ROOT / "logs"
ICON_PNG = ROOT / "extension" / "icons" / "icon128.png"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "tray.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("subfish.tray")


def _pythonw():
    exe = ROOT / "venv" / "Scripts" / "pythonw.exe"
    return str(exe) if exe.exists() else sys.executable


def _python():
    exe = ROOT / "venv" / "Scripts" / "python.exe"
    return str(exe) if exe.exists() else sys.executable


class Supervisor:
    """拉起/看护服务与小窗；不再需要控制台窗口。"""

    def __init__(self):
        LOG_DIR.mkdir(exist_ok=True)
        self.svc = None
        self.widget = None
        self._watch = threading.Thread(target=self._watchdog, daemon=True)
        self._watch.start()

    # ---------- 进程管理 ----------
    def service_running(self):
        if self.svc and self.svc.poll() is None:
            return True
        # 也可能是别人（比如手动跑的）起的，探一下端口
        return self._port_open(8766)

    @staticmethod
    def _port_open(port, host="127.0.0.1", timeout=0.4):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def start_service(self):
        if self.service_running():
            log.info("服务已在运行")
            return
        out = open(LOG_DIR / "server.log", "a", encoding="utf-8")
        self.svc = subprocess.Popen(
            [_pythonw(), "-m", "server.main"],
            cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
        )
        log.info("已启动服务 pid=%s（日志 logs\\server.log）", self.svc.pid)

    def stop_service(self):
        for p in (self.svc,):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
        self.svc = None
        log.info("已停止服务")

    def start_widget(self):
        if self.widget and self.widget.poll() is None:
            return
        self.widget = subprocess.Popen(
            [_pythonw(), "-m", "widget.widget"], cwd=str(ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log.info("已拉起字幕小窗 pid=%s", self.widget.pid)

    def stop_widget(self):
        if self.widget and self.widget.poll() is None:
            self.widget.terminate()
        self.widget = None

    def stop_all(self):
        self.stop_widget()
        self.stop_service()

    def _watchdog(self):
        """小窗被关掉就拉回，但至少间隔 60s，避免和单实例锁打架开出重复窗口。"""
        last = 0.0
        while True:
            time.sleep(5)
            if not self.service_running():
                continue
            if not self.widget or self.widget.poll() is not None:
                if time.time() - last < 60:
                    continue
                last = time.time()
                self.start_widget()

def main():
    import pystray
    from PIL import Image

    sup = Supervisor()
    sup.start_service()
    time.sleep(1.5)
    sup.start_widget()

    image = Image.open(ICON_PNG) if ICON_PNG.exists() else Image.new(
        "RGBA", (64, 64), (18, 22, 31, 255))

    def status_text(item):
        return f"SubFish · 服务{'运行中' if sup.service_running() else '未运行'}"

    def toggle_service(icon, item):
        if sup.service_running():
            sup.stop_service()
        else:
            sup.start_service()
            time.sleep(1.2)
            sup.start_widget()
        icon.update_menu()

    def reopen_widget(icon, item):
        sup.stop_widget()
        sup.start_widget()

    def open_logs(icon, item):
        subprocess.Popen(["explorer", str(LOG_DIR)])

    def quit_all(icon, item):
        sup.stop_all()
        icon.stop()

    icon = pystray.Icon(
        "SubFish", image, "SubFish 实时字幕",
        menu=pystray.Menu(
            pystray.MenuItem(status_text, lambda *_: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("启动服务 / 停止服务", toggle_service),
            pystray.MenuItem("重新拉起字幕小窗", reopen_widget),
            pystray.MenuItem("打开字幕日志目录", open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", quit_all),
        ),
    )
    log.info("托盘已就绪")
    icon.run()


if __name__ == "__main__":
    main()
