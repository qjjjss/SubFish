"""生成测试音频：16kHz 单声道 16-bit wav。

内容是合成的"类语音"能量包络（有声/静音交替），只用于验证 M1 音频链路
（帧率、电平、传输），不含真实语音；M2 起测识别效果请用麦克风或真实录音。
"""
import wave
from pathlib import Path

import numpy as np


def main():
    sr = 16000
    duration = 10.0
    n = int(sr * duration)
    sig = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(42)

    pos = int(0.5 * sr)
    for _ in range(6):
        blen = int(rng.uniform(0.4, 1.5) * sr)
        if pos + blen >= n:
            break
        tt = np.arange(blen) / sr
        f0 = rng.uniform(110.0, 220.0)
        tonal = np.sin(2 * np.pi * f0 * tt) + 0.5 * np.sin(2 * np.pi * 2 * f0 * tt)
        noise = rng.standard_normal(blen).astype(np.float32)
        env = np.ones(blen, dtype=np.float32)
        fade = int(0.05 * sr)
        env[:fade] = np.linspace(0.2, 1.0, fade)
        env[-fade:] = np.linspace(1.0, 0.2, fade)
        sig[pos:pos + blen] = (0.6 * noise + 0.4 * tonal * noise) * env * 0.4
        pos += blen + int(rng.uniform(0.6, 1.2) * sr)

    pcm = np.clip(sig, -1.0, 1.0)
    pcm16 = (pcm * 32767).astype(np.int16)
    out = Path(__file__).resolve().parent.parent / "test_audio" / "test_sample.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())
    print(f"written: {out} ({duration:.1f}s, {sr} Hz mono)")


if __name__ == "__main__":
    main()
