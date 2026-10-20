"""音频处理管线。

数据流：
    PCM 帧 -> [VAD 逐帧检测] -> 语音段 -> [ASR] -> 文本 -> [M3 翻译] -> 字幕事件
统计事件每秒推送一次（rate = 音频毫秒 / 墙钟毫秒，1.0 即实时）。
"""
import logging
import queue
import threading
import time

from .audio import rms

log = logging.getLogger("subfish.pipeline")


class Pipeline:
    def __init__(self, cfg, on_event, on_segment=None):
        self.cfg = cfg
        self._on_event = on_event
        self._on_segment = on_segment
        self.frame_processor = None      # 由 main 注入 VAD.push
        self._lock = threading.Lock()
        self.chunks = 0
        self.bytes_in = 0
        self.audio_ms = 0.0
        self.segments = 0
        self.source_label = None
        self.started_at = time.time()
        self._last_stat = time.time()
        self._audio_ms_at_stat = 0.0
        self._last_rms = 0.0
        self._seg_q = queue.Queue()
        self._worker = threading.Thread(target=self._seg_worker, daemon=True, name="seg-worker")
        self._worker.start()

    def set_source(self, label):
        """设置/清除当前音源标签（如 wav:xxx.wav / mic / extension）。"""
        with self._lock:
            self.source_label = label

    def feed_pcm(self, pcm):
        """喂入 16kHz 单声道 s16le PCM，任意线程可调用。"""
        if not pcm:
            return
        now = time.time()
        with self._lock:
            self.chunks += 1
            self.bytes_in += len(pcm)
            self.audio_ms += len(pcm) / (self.cfg["audio"]["sample_rate"] * 2) * 1000
            self._last_rms = rms(pcm)
        if now - self._last_stat >= 1.0:
            with self._lock:
                elapsed = max(now - self._last_stat, 1e-6)
                rate = (self.audio_ms - self._audio_ms_at_stat) / (elapsed * 1000)
                self._audio_ms_at_stat = self.audio_ms
                self._last_stat = now
                self._emit({
                    "type": "stat",
                    "chunks": self.chunks,
                    "bytes": self.bytes_in,
                    "rate": round(rate, 2),
                    "rms": round(self._last_rms, 4),
                    "source": self.source_label,
                })
        if self.frame_processor:
            self.frame_processor(pcm)

    def handle_segment(self, seg_pcm):
        """VAD 在语音结束时调用：入队，由工作线程串行处理（保序、不阻塞音频入口）。"""
        with self._lock:
            self.segments += 1
        self._seg_q.put(seg_pcm)

    def _seg_worker(self):
        while True:
            seg = self._seg_q.get()
            if self._on_segment is None:
                continue
            try:
                self._on_segment(seg)
            except Exception:
                log.exception("语音段处理失败")

    def _emit(self, event):
        event.setdefault("ts", round(time.time(), 3))
        self._on_event(event)
