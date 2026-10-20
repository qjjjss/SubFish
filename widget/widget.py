"""SubFish 字幕小窗：无边框置顶、半透明、可拖拽，订阅 ws://127.0.0.1:8766 字幕事件。

用法（项目根目录）：
    venv\\Scripts\\pythonw.exe -m widget.widget    无控制台窗口
    venv\\Scripts\\python -m widget.widget          带日志输出，便于排查

交互：左键拖拽移动；右键菜单可切换原文显示、置顶、字号、清空、退出。
"""
import asyncio
import atexit
import json
import logging
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

try:
    from server.config import load_config
except ImportError:  # 允许从任意目录启动
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from server.config import load_config

import websockets

log = logging.getLogger("subfish.widget")

BG = "#12161f"
FG = "#f2f5f9"
DIM = "#6b7280"
OK = "#4ade80"
WARN = "#f59e0b"
FONT = "Microsoft YaHei UI"
STATE_FILE = Path(__file__).resolve().parent / "state.json"
WIDTH = 560
HISTORY = 2


class Widget:
    def __init__(self):
        self.cfg = load_config()
        self.uri = f"ws://{self.cfg['server']['host']}:{self.cfg['server']['subtitle_port']}"
        self.state = self._load_state()
        self.queue = queue.Queue()
        self.history = []
        self.connected = False
        self.last_latency = None
        self._pending_src = ""
        self.last_seg_id = None
        self.pending = False
        self._build_ui()
        self._start_client()

    # ---------- 状态持久化 ----------
    def _load_state(self):
        default = {
            "x": None, "y": None, "show_source": True, "topmost": True,
            "font_size": 20, "alpha": 0.93, "width": WIDTH,
        }
        if STATE_FILE.exists():
            try:
                default.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
        return default

    def _save_state(self, pos_only=False):
        try:
            if pos_only:
                self.state["x"] = self.root.winfo_x()
                self.state["y"] = self.root.winfo_y()
            STATE_FILE.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ---------- 界面 ----------
    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("SubFish")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.state["topmost"]))
        self.root.attributes("-alpha", float(self.state["alpha"]))
        self.root.configure(bg=BG)
        self.width = int(self.state["width"])

        self.frame = tk.Frame(self.root, bg=BG)
        self.frame.pack(fill="both", expand=True, padx=18, pady=14)

        wrap = self.width - 36
        self.hist_label = tk.Label(self.frame, text="", bg=BG, fg=DIM, font=(FONT, 11),
                                   justify="left", anchor="w", wraplength=wrap)
        self.hist_label.pack(fill="x")

        self.zh_var = tk.StringVar(value="等待字幕...")
        self.zh_label = tk.Label(self.frame, textvariable=self.zh_var, bg=BG, fg=FG,
                                 font=(FONT, self.state["font_size"], "bold"),
                                 justify="left", anchor="w", wraplength=wrap)
        self.zh_label.pack(fill="x", pady=(6, 2))

        self.src_var = tk.StringVar(value="")
        self.src_label = tk.Label(self.frame, textvariable=self.src_var, bg=BG, fg=DIM,
                                  font=(FONT, 12), justify="left", anchor="w", wraplength=wrap)
        if self.state["show_source"]:
            self.src_label.pack(fill="x")

        self.status_var = tk.StringVar(value="SubFish · 连接中")
        self.status_label = tk.Label(self.frame, textvariable=self.status_var, bg=BG, fg=WARN,
                                     font=(FONT, 9), anchor="w")
        self.status_label.pack(fill="x", pady=(8, 0))

        for w in (self.root, self.frame, self.hist_label, self.zh_label, self.src_label, self.status_label):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<ButtonPress-3>", self._menu)

        self.root.update_idletasks()
        h = self.frame.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if self.width > sw:
            self.width = sw
        x = self.state["x"] if self.state["x"] is not None else (sw - self.width) // 2
        y = self.state["y"] if self.state["y"] is not None else sh - h - 140
        # 记忆的位置可能在拔掉外接屏后落到屏幕外，钳回可视区
        x = max(0, min(int(x), max(0, sw - self.width)))
        y = max(0, min(int(y), max(0, sh - h)))
        self.root.geometry(f"{self.width}x{h}+{x}+{y}")

    def _resize(self):
        self.root.update_idletasks()
        h = self.frame.winfo_reqheight()
        self.root.geometry(f"{self.width}x{h}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    # ---------- 交互 ----------
    def _drag_start(self, event):
        # 偏移按窗口左上角算，点在任意子控件上都不会跳位
        self._dx = event.x_root - self.root.winfo_x()
        self._dy = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")

    def _drag_end(self, _event):
        self._save_state(pos_only=True)

    def _menu(self, event):
        menu = tk.Menu(self.root, tearoff=0, bg="#1c2230", fg=FG,
                       activebackground="#2b3444", activeforeground=FG, bd=0)
        menu.add_command(label="隐藏原文" if self.state["show_source"] else "显示原文",
                         command=self._toggle_source)
        menu.add_command(label="取消置顶" if self.state["topmost"] else "窗口置顶",
                         command=self._toggle_topmost)
        menu.add_separator()
        for size in (16, 20, 26):
            mark = " ✓" if size == self.state["font_size"] else ""
            menu.add_command(label=f"字号 {size}{mark}", command=lambda s=size: self._set_font(s))
        menu.add_separator()

        sub_a = tk.Menu(menu, tearoff=0, bg="#1c2230", fg=FG, activebackground="#2b3444", bd=0)
        for a in (0.7, 0.85, 0.93, 1.0):
            mark = " ✓" if abs(a - self.state["alpha"]) < 0.01 else ""
            sub_a.add_command(label=f"{int(a * 100)}%{mark}", command=lambda v=a: self._set_alpha(v))
        menu.add_cascade(label="透明度", menu=sub_a)

        sub_w = tk.Menu(menu, tearoff=0, bg="#1c2230", fg=FG, activebackground="#2b3444", bd=0)
        for w in (440, 560, 720, 900):
            mark = " ✓" if w == self.width else ""
            sub_w.add_command(label=f"{w}px{mark}", command=lambda v=w: self._set_width(v))
        menu.add_cascade(label="宽度", menu=sub_w)
        menu.add_separator()
        menu.add_command(label="清空字幕", command=self._clear)
        menu.add_command(label="退出", command=self._quit)
        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_source(self):
        self.state["show_source"] = not self.state["show_source"]
        if self.state["show_source"]:
            self.src_label.pack(fill="x", before=self.status_label)
        else:
            self.src_label.pack_forget()
        self.src_var.set(self._pending_src if self.state["show_source"] else "")
        self._save_state()
        self._resize()

    def _toggle_topmost(self):
        self.state["topmost"] = not self.state["topmost"]
        self.root.attributes("-topmost", self.state["topmost"])
        self._save_state()

    def _set_font(self, size):
        self.state["font_size"] = size
        self.zh_label.configure(font=(FONT, size, "bold"))
        self._save_state()
        self._resize()

    def _set_alpha(self, alpha):
        self.state["alpha"] = alpha
        self.root.attributes("-alpha", alpha)
        self._save_state()

    def _set_width(self, width):
        self.state["width"] = width
        self.width = width
        wrap = width - 36
        for lab in (self.hist_label, self.zh_label, self.src_label):
            lab.configure(wraplength=wrap)
        self._resize()
        self._save_state()

    def _clear(self):
        self.history.clear()
        self.hist_label.configure(text="")
        self.zh_var.set("等待字幕...")
        self.src_var.set("")
        self._resize()

    def _quit(self):
        self._save_state()
        self.root.destroy()

    # ---------- 字幕事件 ----------
    def _start_client(self):
        threading.Thread(target=lambda: asyncio.run(self._client()), daemon=True).start()

    async def _client(self):
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(self.uri, ping_interval=20, ping_timeout=20) as ws:
                    log.info("已连接字幕服务 %s", self.uri)
                    self.queue.put({"kind": "status", "connected": True})
                    backoff = 1.0
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except ValueError:
                            continue
                        self.queue.put({"kind": "event", "data": data})
            except Exception as exc:
                log.info("字幕服务断开（%s），%.0fs 后重试", exc, backoff)
                self.queue.put({"kind": "status", "connected": False})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)

    def _handle(self, item):
        if item["kind"] == "status":
            self.connected = item["connected"]
            return
        data = item["data"]
        if data.get("type") != "subtitle":
            return

        seg_id = data.get("seg_id")
        zh = data.get("zh") or ""
        src = data.get("src") or ""
        lang = data.get("lang") or ""
        pending = bool(data.get("pending"))
        self.last_latency = data.get("latency_ms")

        # 同一句话的翻译回来了：原地更新，不再进历史
        if seg_id is not None and seg_id == self.last_seg_id:
            self.pending = pending
            if zh or not pending:
                self.zh_var.set(zh or src)
                if zh:
                    log.info("字幕: %s", zh)
            self._show_source(src, lang)
            self._resize()
            return

        # 新的一句：上一句进历史
        prev = self.zh_var.get()
        if prev and prev != "等待字幕...":
            self.history.append(prev)
            self.history = self.history[-HISTORY:]
            self.hist_label.configure(text="\n".join(self.history))

        self.last_seg_id = seg_id
        self.pending = pending
        if zh:
            log.info("字幕: %s", zh)
            self.zh_var.set(zh)
        else:
            # 先显示识别原文，翻译好了会被原地替换
            log.info("字幕(待译): %s", src)
            self.zh_var.set(src or "…")
        self._show_source(src, lang)
        self._resize()

    def _show_source(self, src, lang):
        show = self.state["show_source"] and src and not lang.startswith("zh")
        self._pending_src = src
        self.src_var.set(src if show else "")

    def _refresh_status(self):
        if self.connected:
            text = "SubFish · 已连接"
            color = OK
            if self.pending:
                text += " · 翻译中…"
            elif self.last_latency:
                text += f" · 延迟 {self.last_latency / 1000:.1f}s"
        else:
            text = "SubFish · 未连接字幕服务（自动重试中）"
            color = WARN
        self.status_var.set(text)
        self.status_label.configure(fg=color)

    def _pump(self):
        try:
            while True:
                self._handle(self.queue.get_nowait())
        except queue.Empty:
            pass
        self._refresh_status()
        self.root.after(100, self._pump)

    def run(self):
        self._pump()
        self.root.mainloop()


LOCK_FILE = Path(__file__).resolve().parent / ".instance.lock"


def _single_instance():
    """只允许一个小窗：第二个实例直接退出，避免托盘看护开出重复窗口。"""
    import os

    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))
        return True
    except FileExistsError:
        # 锁还在但进程可能已经死了（上次被强杀），尝试清理一次
        try:
            LOCK_FILE.unlink(missing_ok=True)
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))
            return True
        except OSError:
            return False
    except OSError:
        return False


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not _single_instance():
        log.warning("已有小窗实例在运行，本次退出（避免重复窗口）")
        return
    Widget().run()


if __name__ == "__main__":
    main()
