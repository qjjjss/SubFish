"""M1 一键自检：启动服务 -> 字幕通道 hello/ping -> 音频通道推 2 秒 PCM -> 收事件 -> 退出。

用法：venv\\Scripts\\python scripts\\smoke_test.py
"""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import websockets

ROOT = Path(__file__).resolve().parent.parent
AUDIO_URI = "ws://127.0.0.1:8765"
SUBTITLE_URI = "ws://127.0.0.1:8766"


async def main():
    print("[smoke] starting server ...")
    proc = subprocess.Popen([sys.executable, "-m", "server.main"], cwd=str(ROOT))
    try:
        await asyncio.sleep(2.0)
        async with websockets.connect(SUBTITLE_URI) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print("[smoke] hello:", hello)
            await ws.send(json.dumps({"type": "ping"}))
            pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print("[smoke] pong:", pong)

            sr = 16000
            t = np.arange(sr * 2) / sr
            pcm = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16).tobytes()
            async with websockets.connect(AUDIO_URI) as aws:
                await aws.send(json.dumps({"type": "start", "tab": "smoke-test"}))
                for i in range(0, len(pcm), 640):
                    await aws.send(pcm[i:i + 640])
                await asyncio.sleep(0.3)
            print("[smoke] 2s PCM pushed")

            deadline = time.time() + 3.0
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                except asyncio.TimeoutError:
                    break
                print("[smoke] event:", msg)
        print("[smoke] OK - M1 pipeline verified")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
