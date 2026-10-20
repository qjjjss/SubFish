"""SubFish 本地服务入口。

用法（在项目根目录）：
    python -m server.main                                        等待 Chrome 扩展接入（正式模式）
    python -m server.main --source wav:test_audio/test_sample.wav --loop    用 wav 当音源（M1 验证）
    python -m server.main --source mic                          用麦克风当音源

通道：
    ws://127.0.0.1:8765   音频入口（扩展/测试源 -> 服务，16kHz 单声道 s16le PCM）
    ws://127.0.0.1:8766   字幕出口（服务 -> 桌面小窗，JSON 事件）
"""
import argparse
import asyncio
import json
import logging
import queue
import threading
import time
import wave
from pathlib import Path

from .audio import frame_bytes, resample
from .config import load_config
from .pipeline import Pipeline

try:  # websockets 新旧两版 API 兼容
    from websockets.asyncio.server import serve as ws_serve
except ImportError:  # pragma: no cover
    from websockets.legacy.server import serve as ws_serve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("subfish")


class Server:
    def __init__(self, cfg):
        self.cfg = cfg
        self._events = queue.Queue()
        self.pipeline = Pipeline(cfg, self._events.put, on_segment=self._process_segment)
        self.subtitle_clients = set()
        self._seg_lock = threading.Lock()
        self._seg_id = 0
        self._last_rate_warn = 0.0
        # 翻译挪到独立线程：ASR 不等翻译，连续说话时不会堆积延迟
        self._trans_q = queue.Queue()
        threading.Thread(target=self._trans_worker, daemon=True, name="trans-worker").start()
        self._init_engines()

    def _init_engines(self):
        from .asr import AsrEngine
        from .logbook import SubtitleLog
        from .translate import Translator
        from .vad import VadSegmenter

        log.info("加载 Whisper 模型...")
        self.asr = AsrEngine(self.cfg)
        self.vad = VadSegmenter(self.cfg, self.pipeline.handle_segment)
        self.pipeline.frame_processor = self.vad.push
        self.translator = Translator(self.cfg)
        if self.cfg["translate"]["engine"] == "ollama":
            ok, err = self.translator.check()
            if ok:
                log.info("Ollama 连接正常（%s）", self.translator.model)
                if self.cfg["translate"]["ollama"].get("warmup", True):
                    # 后台预热：把 7B 模型 load 进显存，第一句字幕就不用等冷启动
                    threading.Thread(
                        target=self.translator.warmup, daemon=True, name="ollama-warmup"
                    ).start()
            else:
                log.warning(
                    "Ollama 连接失败（%s）：请确认 Ollama 已启动且装有模型 %s；翻译将降级为仅显示原文",
                    err, self.translator.model,
                )
        log_dir = Path(self.cfg["log"]["dir"])
        if not log_dir.is_absolute():
            log_dir = Path(__file__).resolve().parent.parent / log_dir
        self.logbook = SubtitleLog(log_dir)
        log.info(
            "音频管线就绪: VAD(threshold=%.2f, silence=%dms) -> Whisper(%s) -> 翻译(%s/%s)",
            self.cfg["vad"]["threshold"], self.cfg["vad"]["silence_ms"],
            self.cfg["asr"]["model"], self.cfg["translate"]["engine"],
            self.translator.model,
        )

    def _next_seg_id(self):
        with self._seg_lock:
            self._seg_id += 1
            return self._seg_id

    def _process_segment(self, seg_pcm):
        """ASR 一完成就先把原文推给小窗（pending），翻译回来后用同一 seg_id 原地更新。"""
        t0 = time.time()
        try:
            text, lang = self.asr.transcribe(seg_pcm)
        except Exception:
            log.exception("ASR 推理失败")
            return
        if not text:
            log.info("语音段无识别结果（%.0fms）", (time.time() - t0) * 1000)
            return

        seg_id = self._next_seg_id()
        asr_ms = round((time.time() - t0) * 1000)
        seg_ms = round(len(seg_pcm) / 32)
        lang = lang or "auto"
        is_zh = lang.startswith("zh")

        if is_zh or not self.cfg["display"].get("partial_first", True):
            zh = text if is_zh else None
            translate_ms = 0
            if not is_zh:
                t1 = time.time()
                zh = self.translator.translate(text, lang)
                translate_ms = round((time.time() - t1) * 1000)
                if zh:
                    self.translator.remember(text, zh)
            self._finish(seg_id, t0, text, lang, zh, asr_ms, translate_ms, seg_ms)
            return

        # 先出原文（小窗立刻有内容），再交给翻译线程
        self._events.put({
            "type": "subtitle", "ts": round(time.time(), 3), "seg_id": seg_id,
            "lang": lang, "src": text, "zh": None, "pending": True,
            "latency_ms": asr_ms, "translate_ms": 0, "seg_ms": seg_ms,
            "source": self.pipeline.source_label,
        })
        self._trans_q.put((seg_id, t0, text, lang, asr_ms, seg_ms))

    def _trans_worker(self):
        while True:
            seg_id, t0, src, lang, asr_ms, seg_ms = self._trans_q.get()
            t1 = time.time()
            zh = self.translator.translate(src, lang)
            translate_ms = round((time.time() - t1) * 1000)
            if zh:
                self.translator.remember(src, zh)
            else:
                log.warning("翻译失败，本段仅显示原文")
            self._finish(seg_id, t0, src, lang, zh, asr_ms, translate_ms, seg_ms)

    def _finish(self, seg_id, t0, src, lang, zh, asr_ms, translate_ms, seg_ms):
        record = {
            "ts": round(time.time(), 3),
            "seg_id": seg_id,
            "lang": lang,
            "src": src,
            "zh": zh,
            "latency_ms": round((time.time() - t0) * 1000),
            "translate_ms": translate_ms,
            "seg_ms": seg_ms,
            "source": self.pipeline.source_label,
            "pending": False,
        }
        self.logbook.append(record)
        self._events.put({**record, "type": "subtitle"})

    async def _event_pump(self):
        loop = asyncio.get_running_loop()
        while True:
            event = await loop.run_in_executor(None, self._events.get)
            await self._broadcast(event)

    async def _broadcast(self, event):
        etype = event.get("type")
        if etype == "subtitle":
            if event.get("pending"):
                log.info(
                    "字幕[%s] 识别%sms（翻译中）: %s",
                    event.get("lang"), event.get("latency_ms"), event.get("src"),
                )
            else:
                log.info(
                    "字幕[%s] 总%sms(译%s): %s",
                    event.get("lang"), event.get("latency_ms"), event.get("translate_ms"),
                    event.get("zh") or event.get("src"),
                )
        elif etype == "log":
            log.info("%s", event.get("note", ""))
        elif etype == "stat":
            rate = event.get("rate") or 0
            now = time.time()
            if 0 < rate < 0.95 and now - self._last_rate_warn > 30:
                self._last_rate_warn = now
                log.warning(
                    "音频到达速率只有 %.2fx：字幕会随时间越来越滞后。"
                    "请把被采集的标签页保持在前台可见（浏览器会限速后台采集）",
                    rate,
                )
        if not self.subtitle_clients:
            return
        msg = json.dumps(event, ensure_ascii=False)
        dead = []
        for ws in list(self.subtitle_clients):
            try:
                await ws.send(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subtitle_clients.discard(ws)

    async def _audio_handler(self, ws):
        log.info("音频通道接入: %s", ws.remote_address)
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    self.pipeline.feed_pcm(bytes(msg))
                else:
                    try:
                        data = json.loads(msg)
                    except ValueError:
                        continue
                    t = data.get("type")
                    if t == "start":
                        self.pipeline.set_source(data.get("tab") or "extension")
                        log.info("开始采集: %s", self.pipeline.source_label)
                    elif t == "stop":
                        self.pipeline.set_source(None)
                        log.info("停止采集")
        except Exception as exc:
            log.info("音频通道断开: %s", exc)
        finally:
            self.pipeline.set_source(None)

    async def _subtitle_handler(self, ws):
        log.info("字幕通道接入: %s", ws.remote_address)
        self.subtitle_clients.add(ws)
        try:
            await ws.send(json.dumps(
                {"type": "hello", "audio_source": self.pipeline.source_label},
                ensure_ascii=False,
            ))
            async for msg in ws:
                try:
                    data = json.loads(msg)
                except ValueError:
                    continue
                if data.get("type") == "ping":
                    await ws.send(json.dumps(
                        {"type": "pong", "ts": round(time.time(), 3)},
                        ensure_ascii=False,
                    ))
        except Exception:
            pass
        finally:
            self.subtitle_clients.discard(ws)
            log.info("字幕通道断开")

    async def serve(self):
        host = self.cfg["server"]["host"]
        pump = asyncio.create_task(self._event_pump())
        audio_srv = await ws_serve(self._audio_handler, host, self.cfg["server"]["audio_port"])
        sub_srv = await ws_serve(self._subtitle_handler, host, self.cfg["server"]["subtitle_port"])
        log.info(
            "SubFish 已启动: 音频 ws://%s:%d | 字幕 ws://%s:%d",
            host, self.cfg["server"]["audio_port"], host, self.cfg["server"]["subtitle_port"],
        )
        log.info("等待音频接入（Chrome 扩展或 --source 测试音源）...")
        await asyncio.gather(pump, audio_srv.wait_closed(), sub_srv.wait_closed())

    async def _wav_source(self, path, loop_play):
        try:
            await self._wav_loop(path, loop_play)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("wav 音源异常，已停止喂音频")

    async def _wav_loop(self, path, loop_play):
        sr_out = self.cfg["audio"]["sample_rate"]
        frame_len = frame_bytes(sr_out, self.cfg["audio"]["frame_ms"])
        chunk_frames = 5  # 每 100ms 喂一次，降低 Windows 定时器精度对节奏的影响
        with wave.open(path, "rb") as w:
            src_rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            log.info("wav 音源: %s (%d Hz, %d 声道)", path, src_rate, ch)
            if width != 2:
                log.error("仅支持 16-bit wav，当前 %d bit", width * 8)
                return
            self.pipeline.set_source(f"wav:{Path(path).name}")
            chunk_ms = self.cfg["audio"]["frame_ms"] * chunk_frames
            # 按源采样率取帧，保证以 1.0x 实时速度喂（源不是 16k 时才不会变慢放）
            src_chunk = max(1, int(src_rate * chunk_ms / 1000))
            next_at = time.monotonic()
            while True:
                frames = w.readframes(src_chunk)
                if not frames:
                    if not loop_play:
                        break
                    w.rewind()
                    continue
                if ch > 1:
                    frames = frames[:: ch * 2]
                if src_rate != sr_out:
                    frames = resample(frames, src_rate, sr_out)
                self.pipeline.feed_pcm(frames)
                next_at += chunk_ms / 1000
                delay = next_at - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
        log.info("wav 音源结束")

    async def _mic_source(self):
        try:
            import sounddevice as sd
        except ImportError:
            log.error("缺少 sounddevice，请先运行 安装依赖.bat")
            return
        sr_out = self.cfg["audio"]["sample_rate"]
        dev_sr = int(sd.query_devices(kind="input")["default_samplerate"])
        log.info("麦克风音源: 设备 %d Hz -> %d Hz", dev_sr, sr_out)

        def callback(indata, frames, time_info, status):
            pcm = bytes(indata)
            if dev_sr != sr_out:
                pcm = resample(pcm, dev_sr, sr_out)
            self.pipeline.feed_pcm(pcm)

        self.pipeline.set_source("mic")
        with sd.RawInputStream(samplerate=dev_sr, channels=1, dtype="int16", callback=callback):
            await asyncio.Event().wait()


async def amain(args):
    cfg = load_config()
    server = Server(cfg)
    if args.source:
        kind, _, value = args.source.partition(":")
        def _spawn(coro, name):
            t = asyncio.create_task(coro, name=name)
            t.add_done_callback(
                lambda task: task.cancelled()
                or task.exception()
                and log.error("%s 任务异常终止: %s", name, task.exception())
            )
            return t

        if kind == "wav":
            if not Path(value).exists():
                log.error("wav 文件不存在: %s", value)
                return
            _spawn(server._wav_source(value, args.loop), "wav-source")
        elif kind == "mic":
            _spawn(server._mic_source(), "mic-source")
        else:
            log.error("未知音源: %s（支持 wav:路径 或 mic）", args.source)
            return
    await server.serve()


def main():
    parser = argparse.ArgumentParser(prog="subfish", description="SubFish 本地服务")
    parser.add_argument("--source", help="测试音源：wav:文件路径 或 mic")
    parser.add_argument("--loop", action="store_true", help="wav 循环播放")
    args = parser.parse_args()
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        log.info("已退出")


if __name__ == "__main__":
    main()
