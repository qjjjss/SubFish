"""语音活动检测（VAD）：Silero VAD v5 ONNX 版，纯 onnxruntime 推理，无需 torch。

模型文件内嵌于 server/models/silero_vad_16k_op15.onnx（源自 silero-vad 官方包）。
切分规则：静音超过 silence_ms 判一句结束；不足 min_speech_ms 的段丢弃；
超过 max_segment_ms 强切；段首尾各留 100ms padding 避免切字。
"""
import logging
import threading
from pathlib import Path

import numpy as np
import onnxruntime as ort

log = logging.getLogger("subfish.vad")

WINDOW = 512            # 16kHz 下 32ms，模型固定窗口
CONTEXT = 64            # 模型要求窗口前拼接上一段末尾 64 采样（官方 OnnxWrapper 行为）
PAD_MS = 100            # 段首尾 padding


class VadSegmenter:
    def __init__(self, cfg, on_segment):
        vad_cfg = cfg["vad"]
        self.threshold = float(vad_cfg["threshold"])
        self.silence_ms = int(vad_cfg["silence_ms"])
        self.min_speech_ms = int(vad_cfg["min_speech_ms"])
        self.max_segment_ms = int(vad_cfg["max_segment_ms"])
        self.sample_rate = int(cfg["audio"]["sample_rate"])
        self.on_segment = on_segment

        model_path = Path(__file__).resolve().parent / "models" / "silero_vad_16k_op15.onnx"
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])

        self._lock = threading.Lock()
        self._pending = bytearray()
        self._buf = np.zeros(0, dtype=np.int16)
        self._dropped = 0
        self._abs_pos = 0
        self._buf_limit = int(self.sample_rate * (self.max_segment_ms + self.silence_ms + 2000) / 1000)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.int16)
        self.last_prob = 0.0
        self._triggered = False
        self._temp_end = 0
        self._seg_start_abs = 0
        self._speech_ms = 0

    def reset(self):
        with self._lock:
            self._pending.clear()
            self._buf = np.zeros(0, dtype=np.int16)
            self._dropped = 0
            self._abs_pos = 0
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._context = np.zeros(CONTEXT, dtype=np.int16)
            self._triggered = False
            self._temp_end = 0
            self._seg_start_abs = 0
            self._speech_ms = 0

    def push(self, pcm: bytes):
        """喂入任意长度 16kHz 单声道 s16le PCM（线程安全）。"""
        if not pcm:
            return
        with self._lock:
            self._pending += pcm
            pending = np.frombuffer(bytes(self._pending), dtype=np.int16)
            n_win = len(pending) // WINDOW
            if n_win == 0:
                return
            consumed = n_win * WINDOW
            del self._pending[: consumed * 2]
            for i in range(n_win):
                self._process_window(pending[i * WINDOW:(i + 1) * WINDOW])

    def _process_window(self, window):
        self._append_buf(window)
        x = np.concatenate([self._context, window]).astype(np.float32) / 32768.0
        out = self.session.run(
            None,
            {
                "input": x.reshape(1, -1),
                "state": self._state,
                "sr": np.array(self.sample_rate, dtype=np.int64),
            },
        )
        self.last_prob = float(np.asarray(out[0]).reshape(-1)[0])
        self._state = np.asarray(out[1], dtype=np.float32)
        self._context = window[-CONTEXT:].copy()

        win_ms = WINDOW * 1000 // self.sample_rate
        if self.last_prob >= self.threshold:
            if not self._triggered:
                self._triggered = True
                self._seg_start_abs = self._abs_pos - WINDOW
                self._speech_ms = 0
                self._temp_end = 0
            self._speech_ms += win_ms
            self._temp_end = 0
        elif self._triggered:
            self._temp_end += win_ms
            if self._temp_end >= self.silence_ms:
                self._emit_segment()
        if self._triggered and self._speech_ms >= self.max_segment_ms:
            self._emit_segment(force=True)

    def _append_buf(self, window):
        self._buf = np.concatenate([self._buf, window]) if self._buf.size else window.copy()
        self._abs_pos += WINDOW
        if self._buf.size > self._buf_limit:
            drop = self._buf.size - self._buf_limit
            self._buf = self._buf[drop:]
            self._dropped += drop

    def _emit_segment(self, force=False):
        silence_samples = int(self.sample_rate * self.silence_ms / 1000)
        pad_samples = int(self.sample_rate * PAD_MS / 1000)
        end_abs = self._abs_pos if force else self._abs_pos - silence_samples + pad_samples
        start_abs = max(self._seg_start_abs - pad_samples, 0)
        dur_ms = (end_abs - start_abs) * 1000 / self.sample_rate

        i0 = max(start_abs - self._dropped, 0)
        i1 = min(end_abs - self._dropped, self._buf.size)
        seg = self._buf[i0:i1] if i1 > i0 else np.zeros(0, dtype=np.int16)

        if dur_ms >= self.min_speech_ms and seg.size:
            self.on_segment(seg.astype(np.int16).tobytes())

        if force:
            self._seg_start_abs = self._abs_pos
            self._speech_ms = 0
            self._temp_end = 0
        else:
            self._triggered = False
            self._temp_end = 0
            self._speech_ms = 0
