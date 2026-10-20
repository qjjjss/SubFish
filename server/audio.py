"""PCM 音频工具：帧长、电平（RMS）、重采样。约定 16kHz 单声道 s16le。"""
import numpy as np


def frame_bytes(sample_rate, frame_ms):
    """每帧字节数（16-bit 单声道）。"""
    return sample_rate * frame_ms // 1000 * 2


def rms(pcm):
    """0~1 的均方根电平，用于判断有没有声音。"""
    if not pcm:
        return 0.0
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr * arr)) / 32768.0)


def resample(pcm, src_rate, dst_rate):
    """线性插值重采样（16-bit 单声道 s16le）。"""
    if src_rate == dst_rate or not pcm:
        return pcm
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if arr.size < 2:
        return pcm
    n_out = max(1, int(len(arr) * dst_rate / src_rate))
    idx = np.clip(np.arange(n_out) * (src_rate / dst_rate), 0, len(arr) - 1)
    out = np.interp(idx, np.arange(len(arr)), arr)
    return out.astype(np.int16).tobytes()
